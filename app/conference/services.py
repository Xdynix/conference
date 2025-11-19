__all__ = (
    "ConferenceService",
    "InvitationService",
)

from collections import defaultdict
from collections.abc import Collection

from django.contrib.auth.models import AnonymousUser
from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from loguru import logger

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, User


class ConferenceService:
    @classmethod
    async def visible_conferences(
        cls,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Conference]:
        """Return the queryset of active conferences visible to ``user``.

        The queryset includes:

        - all public conferences;
        - all conferences when the user is a superuser or holds any ``global_readable``
          role;
        - private conferences where the user is a conference admin; and
        - private conferences where the user is an admin on at least one of the
          conference's tracks.
        """
        conferences = Conference.objects.filter(active=True)

        if not user.is_authenticated:
            return conferences.filter(visibility=Conference.Visibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return conferences

        is_public = Q(visibility=Conference.Visibility.PUBLIC)
        is_conference_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            track__role_assignment__user=user,
            track__role_assignment__role__in=TrackRole.admins(),
        )
        return conferences.filter(
            is_public | is_conference_admin | is_track_admin
        ).distinct()

    @classmethod
    async def visible_tracks(
        cls,
        user: User | AnonymousUser,
        conferences: Collection[Conference] | QuerySet[Conference],
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Track]:
        """Return the queryset of tracks within ``conferences`` visible to ``user``.

        The queryset includes:

        - all public tracks;
        - all tracks when the user is a superuser or holds any ``global_readable`` role;
        - private tracks whose parent conference the user administers; and
        - private tracks where the user has a track-admin role.
        """
        tracks = Track.objects.filter(
            conference__in=conferences,
            conference__active=True,
            active=True,
        )

        if not user.is_authenticated:
            return tracks.filter(visibility=Track.Visibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return tracks

        is_public = Q(visibility=Track.Visibility.PUBLIC)
        is_conference_admin = Q(
            conference__role_assignment__user=user,
            conference__role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=TrackRole.admins(),
        )
        return tracks.filter(
            is_public | is_conference_admin | is_track_admin
        ).distinct()

    @classmethod
    async def prefetch_tracks(
        cls,
        *conferences: Conference,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> Collection[Conference]:
        """Attach track lists to conferences according to ``visible_tracks`` rules."""
        tracks = await cls.visible_tracks(
            user,
            conferences,
            global_readable=global_readable,
        )

        conference_tracks: dict[int, list[Track]] = defaultdict(list)
        async for track in tracks:
            conference_tracks[track.conference_id].append(track)

        for conference in conferences:
            conference.prefetched_tracks = conference_tracks[conference.id]

        return conferences


class InvitationService:
    token_signer = Signer(salt="conference.invitation_code")

    # TODO: Add send-invitation method.

    @classmethod
    def get_invitation_token(cls, invitation: Invitation) -> str:
        """Return a deterministic signed token that represents the invitation."""
        return cls.token_signer.sign(str(invitation.uid))

    @classmethod
    async def retrieve_invitation(cls, token: str) -> Invitation | None:
        """Return the invitation for ``token`` or ``None`` when it is invalid."""
        try:
            invitation_uid = cls.token_signer.unsign(token)
        except BadSignature:
            return None

        return await Invitation.objects.filter(uid=invitation_uid).afirst()

    @classmethod
    @logger.catch(reraise=True)
    def redeem_invitation(cls, invitation: Invitation, user: User) -> bool:
        """Redeem an invitation by assigning roles to the user.

        The invitation becomes accepted if it is currently pending or previously
        rejected. Already accepted invitations remain unchanged.

        Args:
            invitation: The invitation to redeem. Must be in ``PENDING`` or ``REJECTED``
                status.
            user: The user redeeming the invitation.

        Returns:
            ``True`` if the invitation was accepted during this call, ``False`` if it
            was already accepted.
        """
        with transaction.atomic():
            # Lock the invitation row to prevent concurrent redemption.
            invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)

            if invitation.status == Invitation.Status.ACCEPTED:
                return False

            invitation.invitee_user = user
            invitation.accept_time = timezone.now()
            invitation.save(update_fields=["invitee_user", "accept_time"])

            conference_role_assignments = [
                ConferenceRoleAssignment(
                    conference=invitation.conference,
                    user=user,
                    role=role,
                )
                for role in invitation.conference_role_entries.values_list(
                    "role", flat=True
                )
            ]
            ConferenceRoleAssignment.objects.bulk_create(
                conference_role_assignments,
                ignore_conflicts=True,
            )

            entries = invitation.track_role_entries
            track_role_assignments = [
                TrackRoleAssignment(
                    track_id=track_id,
                    user=user,
                    role=role,
                )
                for track_id, role in entries.values_list("track_id", "role")
            ]
            TrackRoleAssignment.objects.bulk_create(
                track_role_assignments,
                ignore_conflicts=True,
            )

            return True

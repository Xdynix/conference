from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, User


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

    @classmethod
    async def visible_invitations(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Invitation]:
        """Return invitations for the conference visible to the user.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all invitations.
        - Conference admins (chairs and secretaries) see all invitations.
        - Track admins see invitations that contain ONLY track roles for their tracks
          (no conference roles).
        - Other users see no invitations.
        """
        invitations = conference.invitations.all()

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return invitations

        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()
        if is_conference_admin:
            return invitations

        administered_track_ids = [
            track_id
            async for track_id in conference.tracks.filter(
                role_assignment__user=user,
                role_assignment__role__in=TrackRole.admins(),
            )
            .distinct()
            .values_list("pk", flat=True)
        ]

        if not administered_track_ids:
            return invitations.none()

        conference_roles = InvitationConferenceRoleEntry.objects.filter(
            invitation=OuterRef("pk")
        )
        administered_track_roles = InvitationTrackRoleEntry.objects.filter(
            invitation=OuterRef("pk"),
            track_id__in=administered_track_ids,
        )
        other_track_roles = InvitationTrackRoleEntry.objects.filter(
            invitation=OuterRef("pk")
        ).exclude(track_id__in=administered_track_ids)

        return invitations.annotate(
            has_conference_roles=Exists(conference_roles),
            has_administered_track_roles=Exists(administered_track_roles),
            has_other_track_roles=Exists(other_track_roles),
        ).filter(
            has_administered_track_roles=True,
            has_other_track_roles=False,
            has_conference_roles=False,
        )

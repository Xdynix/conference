__all__ = (
    "ConferencePermissionService",
    "InvitationService",
)

from collections.abc import Container

from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.utils import timezone
from loguru import logger

from app.conference.models import (
    Conference,
    ConferenceRoleAssignment,
    Invitation,
    Track,
    TrackRoleAssignment,
)
from app.core.models import Permission, User


class ConferencePermissionService:
    @classmethod
    async def get_conference_permissions(
        cls,
        user: User | AnonymousUser,
        conference: Conference,
    ) -> Container[str]:
        """Return the conference-scoped permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(
                conferencerole__assignment__user=user,
                conferencerole__assignment__conference=conference,
            )

        return await Permission.to_keys(permissions)

    @classmethod
    async def get_track_permissions(
        cls,
        user: User | AnonymousUser,
        track: Track,
    ) -> Container[str]:
        """Return the track-scoped permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(
                trackrole__assignment__user=user,
                trackrole__assignment__track=track,
            )

        return await Permission.to_keys(permissions)


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
    @sync_to_async
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
                    user=user,
                    conference=invitation.conference,
                    role=role,
                )
                for role in invitation.conference_roles.all()
            ]
            ConferenceRoleAssignment.objects.bulk_create(
                conference_role_assignments,
                ignore_conflicts=True,
            )

            track_role_assignments = []
            for track_entry in invitation.track_entries.select_related(
                "track"
            ).prefetch_related("roles"):
                for role in track_entry.roles.all():
                    track_role_assignments.append(
                        TrackRoleAssignment(
                            track=track_entry.track,
                            user=user,
                            role=role,
                        )
                    )
            TrackRoleAssignment.objects.bulk_create(
                track_role_assignments,
                ignore_conflicts=True,
            )

            return True

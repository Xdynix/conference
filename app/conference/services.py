__all__ = ("InvitationService",)

from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.utils import timezone
from loguru import logger

from app.conference.models import (
    ConferenceRoleAssignment,
    Invitation,
    TrackRoleAssignment,
)
from app.core.models import User


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

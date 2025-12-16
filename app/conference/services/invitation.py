from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from enum import StrEnum
from typing import Self

from django.conf import settings
from django.core.signing import BadSignature, Signer
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from loguru import logger
from pydantic import BaseModel, ConfigDict, HttpUrl
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, User
from app.infra.models import Mutex
from app.utils.email import EmailContext, EmailTemplate

from .access import ConferenceAccessService
from .conference import ConferenceService, InsufficientRolePermission


class DuplicateInvitation(Exception):
    pass


class ImmutableInvitation(Exception):
    pass


class InvitationEmailContext(EmailContext):
    site_name: str
    conference_name: str
    conference_display_name: str
    given_name: str
    family_name: str
    affiliation: str
    accept_url: HttpUrl
    reject_url: HttpUrl

    @classmethod
    def sample(
        cls,
        *,
        invitation_accept_page_url: str,
        invitation_reject_page_url: str,
    ) -> Self:
        return cls(
            site_name=settings.SITE_NAME,
            conference_name="Sample Conference",
            conference_display_name="Sample Conference 2025",
            given_name="John",
            family_name="Doe",
            affiliation="Sample University",
            accept_url=HttpUrl(f"{invitation_accept_page_url}#sample-token"),
            reject_url=HttpUrl(f"{invitation_reject_page_url}#sample-token"),
        )


class SendInvitationStatus(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class SendInvitationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    invitation: ULID
    status: SendInvitationStatus
    invitee_email: str | None = None
    reason: str | None = None


class InvitationService:
    token_signer = Signer(salt="conference.invitation_code")

    # Note: Service methods assume the conference is active. API layer validates
    # conference active status via Conference.objects.active(). Service methods do not
    # re-validate conference active status for consistency with how conference roles are
    # handled (we trust the caller has validated the conference object).

    # TODO: Review whether to enforce conference active check in service layer for
    #  defense in depth, especially for methods called outside API endpoints (Django
    #  admin, management commands, background jobs).
    # TODO: Add a non-destructive invitation cancel/revoke flow that preserves history
    #  but blocks redemption and further delivery.

    @classmethod
    @transaction.atomic
    def create_invitation(
        cls,
        *,
        conference: Conference,
        inviter: User,
        invitee_email: str,
        given_name: str = "",
        family_name: str = "",
        affiliation: str = "",
        region_code: str = "",
        desired_paper_count: int = 5,
        interested_keywords: Collection[Keyword] = (),
        conference_roles: Collection[ConferenceRole] = (),
        track_roles: Mapping[Track, Collection[TrackRole]] | None = None,
    ) -> Invitation:
        """Creates a new invitation with the specified roles and profile data.

        Raises:
            DuplicateInvitation: If a pending invitation already exists for this
                conference and email.
            ValueError: If tracks do not belong to the conference.
            InsufficientRolePermission: If the inviter lacks permission to assign the
                specified roles.
        """
        ConferenceService.validate_can_assign_roles(
            user=inviter,
            conference=conference,
            conference_roles=conference_roles,
            track_roles=track_roles,
        )

        try:
            invitation = Invitation.objects.create(
                conference=conference,
                inviter=inviter,
                invitee_email=invitee_email,
                given_name=given_name,
                family_name=family_name,
                affiliation=affiliation,
                region_code=region_code,
                desired_paper_count=desired_paper_count,
            )
        except IntegrityError as exc:
            raise DuplicateInvitation(
                _("A pending invitation already exists for this conference and email.")
            ) from exc

        if interested_keywords:
            invitation.interested_keywords.set(interested_keywords)

        conference_role_entries = [
            InvitationConferenceRoleEntry(
                invitation=invitation,
                role=role,
            )
            for role in set(conference_roles)
        ]
        if conference_role_entries:
            InvitationConferenceRoleEntry.objects.bulk_create(
                conference_role_entries,
                ignore_conflicts=True,
            )

        track_role_entries = [
            InvitationTrackRoleEntry(
                invitation=invitation,
                track=track,
                role=role,
            )
            for track, roles in (track_roles or {}).items()
            for role in set(roles)
        ]
        if track_role_entries:
            InvitationTrackRoleEntry.objects.bulk_create(
                track_role_entries,
                ignore_conflicts=True,
            )

        return invitation

    @classmethod
    def update_invitation(
        cls,
        *,
        invitation_uid: ULID,
        user: User,
        given_name: str | None = None,
        family_name: str | None = None,
        affiliation: str | None = None,
        region_code: str | None = None,
        desired_paper_count: int | None = None,
        interested_keywords: Collection[Keyword] | None = None,
        conference_roles: Collection[ConferenceRole] | None = None,
        track_roles: Mapping[Track, Collection[TrackRole]] | None = None,
    ) -> Invitation:
        """Updates an invitation with new profile data and/or roles.

        The invitee email cannot be changed after creation.

        Raises:
            Invitation.DoesNotExist: If the invitation is not found.
            ImmutableInvitation: If the invitation is not mutable (state is ACCEPTED).
            ValueError: If tracks do not belong to the conference.
            InsufficientRolePermission: If the user lacks permission to manage the
                current or new roles.
        """
        with Mutex.lock_in_transaction(str(invitation_uid), namespace="invitation"):
            invitation = Invitation.objects.get(uid=invitation_uid)

            if not invitation.mutable:
                raise ImmutableInvitation(_("Cannot update accepted invitation."))

            current_conference_roles, current_track_roles = cls.get_invitation_roles(
                invitation
            )
            try:
                ConferenceService.validate_can_assign_roles(
                    user=user,
                    conference=invitation.conference,
                    conference_roles=current_conference_roles,
                    track_roles=current_track_roles,
                )
            except InsufficientRolePermission as exc:
                raise InsufficientRolePermission(
                    _("You cannot manage this invitation.")
                ) from exc

            new_conference_roles = (
                conference_roles
                if conference_roles is not None
                else current_conference_roles
            )
            new_track_roles = (
                track_roles if track_roles is not None else current_track_roles
            )
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=invitation.conference,
                conference_roles=new_conference_roles,
                track_roles=new_track_roles,
            )

            update_fields = []
            if given_name is not None:
                invitation.given_name = given_name
                update_fields.append("given_name")
            if family_name is not None:
                invitation.family_name = family_name
                update_fields.append("family_name")
            if affiliation is not None:
                invitation.affiliation = affiliation
                update_fields.append("affiliation")
            if region_code is not None:
                invitation.region_code = region_code
                update_fields.append("region_code")
            if desired_paper_count is not None:
                invitation.desired_paper_count = desired_paper_count
                update_fields.append("desired_paper_count")

            if update_fields:
                invitation.save(update_fields=update_fields)

            if interested_keywords is not None:
                invitation.interested_keywords.set(interested_keywords)

            if conference_roles is not None:
                invitation.conference_role_entries.all().delete()
                conference_role_entries = [
                    InvitationConferenceRoleEntry(
                        invitation=invitation,
                        role=role,
                    )
                    for role in set(conference_roles)
                ]
                InvitationConferenceRoleEntry.objects.bulk_create(
                    conference_role_entries,
                    ignore_conflicts=True,
                )

            if track_roles is not None:
                invitation.track_role_entries.all().delete()
                track_role_entries = [
                    InvitationTrackRoleEntry(
                        invitation=invitation,
                        track=track,
                        role=role,
                    )
                    for track, roles in track_roles.items()
                    for role in set(roles)
                ]
                InvitationTrackRoleEntry.objects.bulk_create(
                    track_role_entries,
                    ignore_conflicts=True,
                )

            return invitation

    @classmethod
    def delete_invitation(cls, *, invitation_uid: ULID, user: User) -> None:
        """Delete an invitation after validating management permissions.

        Raises:
            Invitation.DoesNotExist: If the invitation is not found.
            InsufficientRolePermission: If the user cannot manage the invitation's
                roles.
        """
        with Mutex.lock_in_transaction(str(invitation_uid), namespace="invitation"):
            invitation = Invitation.objects.get(uid=invitation_uid)

            conference_roles, track_roles = cls.get_invitation_roles(invitation)
            try:
                ConferenceService.validate_can_assign_roles(
                    user=user,
                    conference=invitation.conference,
                    conference_roles=conference_roles,
                    track_roles=track_roles,
                )
            except InsufficientRolePermission as exc:
                raise InsufficientRolePermission(
                    _("You cannot manage this invitation.")
                ) from exc

            invitation.delete()

    @classmethod
    def get_invitation_roles(
        cls,
        invitation: Invitation,
    ) -> tuple[list[str], dict[Track, list[str]]]:
        """Extract roles from an invitation for permission checking.

        Returns:
            Tuple of ``(conference_roles, track_roles)`` where conference_roles is a
            list of ``ConferenceRole`` and ``track_roles`` is a dict mapping ``Track``
            to list of ``TrackRole``. Format matches ``validate_can_assign_roles``
            parameters.
        """
        conference_roles = [
            entry.role for entry in invitation.conference_role_entries.all()
        ]

        track_roles_dict: dict[Track, list[str]] = defaultdict(list)
        for entry in invitation.track_role_entries.select_related("track").filter(
            track__active=True,
        ):
            track_roles_dict[entry.track].append(entry.role)

        return conference_roles, dict(track_roles_dict)

    @classmethod
    def get_invitation_token(cls, invitation: Invitation) -> str:
        """Return a deterministic signed token that represents the invitation."""
        return cls.token_signer.sign(str(invitation.uid))

    @classmethod
    def _build_email_context(
        cls,
        invitation: Invitation,
        *,
        invitation_accept_page_url: str,
        invitation_reject_page_url: str,
    ) -> InvitationEmailContext:
        """Build email context for an invitation."""
        token = cls.get_invitation_token(invitation)
        return InvitationEmailContext(
            site_name=settings.SITE_NAME,
            conference_name=invitation.conference.name,
            conference_display_name=invitation.conference.display_name,
            given_name=invitation.given_name,
            family_name=invitation.family_name,
            affiliation=invitation.affiliation,
            accept_url=HttpUrl(f"{invitation_accept_page_url}#{token}"),
            reject_url=HttpUrl(f"{invitation_reject_page_url}#{token}"),
        )

    @classmethod
    def send_invitation(
        cls,
        invitation_uid: ULID,
        *,
        template: EmailTemplate,
        invitation_accept_page_url: str,
        invitation_reject_page_url: str,
        cc: Sequence[str] = (),
        force_send_to_rejected: bool = False,
        force_send_to_recent: bool = False,
    ) -> tuple[bool, str]:
        """Send an invitation email and update tracking.

        Returns:
            Tuple of ``(sent, invitee_email)`` where ``sent`` is ``True`` if email was
            sent, ``False`` if skipped due to rate limiting or rejected state.

        Raises:
            Invitation.DoesNotExist: If invitation not found.
            ImmutableInvitation: If the invitation is already accepted.
        """
        with Mutex.lock_in_transaction(str(invitation_uid), namespace="invitation"):
            invitation = Invitation.objects.select_related("conference").get(
                uid=invitation_uid
            )

            if invitation.state == Invitation.State.ACCEPTED:
                raise ImmutableInvitation(
                    _("Cannot send invitation that has already been accepted.")
                )

            if (
                invitation.state == Invitation.State.REJECTED
                and not force_send_to_rejected
            ):
                return False, invitation.invitee_email

            now = timezone.now()
            if (
                invitation.last_email_send_time is not None
                and (now - invitation.last_email_send_time)
                <= settings.INVITATION_EMAIL_INTERVAL
                and not force_send_to_recent
            ):
                return False, invitation.invitee_email

            context = cls._build_email_context(
                invitation,
                invitation_accept_page_url=invitation_accept_page_url,
                invitation_reject_page_url=invitation_reject_page_url,
            )
            rendered = template.render(context)
            email_message = rendered.build_message(to=invitation.invitee_email, cc=cc)

            invitation.last_email_send_time = now
            invitation.email_send_count = F("email_send_count") + 1
            invitation.save(
                update_fields=[
                    "update_time",
                    "last_email_send_time",
                    "email_send_count",
                ]
            )

            transaction.on_commit(email_message.send)

            return True, invitation.invitee_email

    @classmethod
    def send_invitations(
        cls,
        invitation_uids: Sequence[ULID],
        *,
        template: EmailTemplate,
        invitation_accept_page_url: str,
        invitation_reject_page_url: str,
        cc: Sequence[str] = (),
        force_send_to_rejected: bool = False,
        force_send_to_recent: bool = False,
    ) -> list[SendInvitationResult]:
        """Send emails for multiple invitations.

        Each invitation is processed in its own transaction. Failures are isolated and
        do not affect other invitations.
        """
        results: list[SendInvitationResult] = []

        for uid in invitation_uids:
            try:
                sent, invitee_email = cls.send_invitation(
                    uid,
                    template=template,
                    invitation_accept_page_url=invitation_accept_page_url,
                    invitation_reject_page_url=invitation_reject_page_url,
                    cc=cc,
                    force_send_to_rejected=force_send_to_rejected,
                    force_send_to_recent=force_send_to_recent,
                )
            except Invitation.DoesNotExist:
                results.append(
                    SendInvitationResult(
                        invitation=uid,
                        status=SendInvitationStatus.NOT_FOUND,
                        reason=_("Invitation not found."),
                    )
                )
            except ImmutableInvitation as exc:
                results.append(
                    SendInvitationResult(
                        invitation=uid,
                        status=SendInvitationStatus.SKIPPED,
                        reason=str(exc),
                    )
                )
            except Exception:
                logger.exception(
                    "Unknown error when sending invitation.",
                    invitation_uid=uid,
                )
                results.append(
                    SendInvitationResult(
                        invitation=uid,
                        status=SendInvitationStatus.FAILED,
                        reason=_("An unexpected error has occurred."),
                    )
                )
            else:
                if sent:
                    results.append(
                        SendInvitationResult(
                            invitation=uid,
                            status=SendInvitationStatus.SENT,
                            invitee_email=invitee_email,
                        )
                    )
                else:
                    results.append(
                        SendInvitationResult(
                            invitation=uid,
                            status=SendInvitationStatus.SKIPPED,
                            invitee_email=invitee_email,
                            reason=_("Skipped due to rate limiting or rejected state."),
                        )
                    )

        return results

    @classmethod
    def retrieve_invitation(cls, token: str) -> Invitation | None:
        """Return the invitation for ``token`` or ``None`` when it is invalid."""
        try:
            invitation_uid = cls.token_signer.unsign(token)
        except BadSignature:
            return None

        return Invitation.objects.filter(
            uid=invitation_uid,
            conference__active=True,
        ).first()

    @classmethod
    def redeem_invitation(cls, invitation: Invitation, user: User) -> bool:
        """Redeem an invitation by assigning roles to the user.

        The invitation becomes accepted if it is currently pending or previously
        rejected. Already accepted invitations remain unchanged.

        Args:
            invitation: The invitation to redeem. Must be in ``PENDING`` or ``REJECTED``
                state.
            user: The user redeeming the invitation.

        Returns:
            ``True`` if the invitation was accepted during this call, ``False`` if it
            was already accepted.
        """
        with (
            Mutex.lock_in_transaction(str(invitation.uid), namespace="invitation"),
            Mutex.lock_in_transaction(str(user.pk), namespace="user_role_assignments"),
        ):
            invitation = Invitation.objects.get(pk=invitation.pk)

            if invitation.state == Invitation.State.ACCEPTED:
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

            entries = invitation.track_role_entries.select_related("track").filter(
                track__active=True,
            )
            # Defensive: track entries should always belong to the invitation's
            # conference. If not, something outside normal flows (manual edits,
            # migrations) has tampered with data; fail loudly.
            for entry in entries:
                if entry.track.conference_id != invitation.conference_id:
                    raise RuntimeError(
                        "Invitation track role does not belong to "
                        f"invitation conference. {invitation.uid=}"
                    )

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

        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=user,
            global_roles=global_readable,
        )

        if ctx.has_full_conference_scope:
            return invitations

        if not ctx.administered_track_ids:
            return invitations.none()

        conference_roles = InvitationConferenceRoleEntry.objects.filter(
            invitation=OuterRef("pk")
        )
        administered_track_roles = InvitationTrackRoleEntry.objects.filter(
            invitation=OuterRef("pk"),
            track__active=True,
            track_id__in=ctx.administered_track_ids,
        )
        other_track_roles = InvitationTrackRoleEntry.objects.filter(
            invitation=OuterRef("pk"),
            track__active=True,
        ).exclude(track_id__in=ctx.administered_track_ids)

        return invitations.annotate(
            has_conference_roles=Exists(conference_roles),
            has_administered_track_roles=Exists(administered_track_roles),
            has_other_track_roles=Exists(other_track_roles),
        ).filter(
            has_administered_track_roles=True,
            has_other_track_roles=False,
            has_conference_roles=False,
        )

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.models import Invitation
from app.conference.services import InvitationService
from app.conference.types import (
    ConferenceDisplayName,
    ConferenceName,
    Profile,
    UserConferenceProfile,
)
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest, EmailStr, HttpRequest
from app.ninja.errors import ErrorResponse
from app.verikit.services import EmailVerificationService

from .core import InvitationUrlsMixin, prefetch_invitation, router


class InvitationTokenPayload(Schema):
    invitation_token: str


class ConferenceSummary(Schema):
    name: ConferenceName
    display_name: ConferenceDisplayName


class InvitationSummary(InvitationUrlsMixin, UserConferenceProfile, Profile):
    uid: ULID
    state: Invitation.State
    invitee_email: EmailStr
    has_existing_account: bool
    conference: ConferenceSummary
    verified_email_token: str | None = None

    @staticmethod
    def resolve_interested_keywords(invitation: Invitation) -> list[str]:
        return [keyword.text for keyword in invitation.interested_keywords.all()]

    @staticmethod
    def resolve_verified_email_token(invitation: Invitation) -> str | None:
        # Clicking an invitation link is equivalent proof of email access as clicking a
        # verification code link. If the link is leaked, an attacker could claim the
        # email during signup, but the legitimate owner can always recover via password
        # reset (which uses a separate token flow). The 30-min token expiry limits the
        # window. This tradeoff is acceptable for the UX improvement of skipping email
        # verification when signing up via invitation.
        if invitation.state == Invitation.State.ACCEPTED:
            return None
        return EmailVerificationService.issue_token(invitation.invitee_email)


@router.post(
    "/invitations:lookup",
    response=InvitationSummary,
    summary="Lookup Invitation",
)
async def lookup_invitation(
    request: HttpRequest,
    payload: InvitationTokenPayload,
) -> Invitation:
    """Retrieve an invitation by token."""
    # Use POST with a body instead of GET/path params so the token stays out of URLs
    # and access logs. The RPC-style path is intentional to protect the secret token.
    invitation = await sync_to_async(InvitationService.retrieve_invitation)(
        payload.invitation_token
    )
    if invitation is None:
        raise Http404

    # This intentionally reveals conference name/display to anyone holding the token,
    # even when the conference is not public.
    return await prefetch_invitation(invitation, request)


@router.post(
    "/invitations:redeem",
    response={
        HTTPStatus.NO_CONTENT: None,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Redeem Invitation",
    auth=is_authenticated,
)
async def redeem_invitation(
    request: AuthedHttpRequest,
    payload: InvitationTokenPayload,
) -> tuple[int, None]:
    """Redeem an invitation using its token."""
    invitation = await sync_to_async(InvitationService.retrieve_invitation)(
        payload.invitation_token
    )
    if invitation is None:
        raise Http404

    user = await request.auser()
    if invitation.invitee_user_id and invitation.invitee_user_id != user.id:
        logger.warning(
            "Invitation already redeemed by another user.",
            invitation_uid=invitation.uid,
            attempted_user_uid=user.uid,
            invitee_user_id=invitation.invitee_user_id,
        )
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("Invitation already redeemed by another user."),
        )

    await sync_to_async(InvitationService.redeem_invitation)(invitation, user)

    logger.info(
        "Invitation redeemed via token.",
        invitation_uid=invitation.uid,
        conference_id=invitation.conference_id,
        user_uid=user.uid,
    )

    return HTTPStatus.NO_CONTENT, None


@router.post(
    "/invitations:reject",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Reject Invitation",
)
async def reject_invitation(
    request: HttpRequest,  # noqa: ARG001
    payload: InvitationTokenPayload,
) -> tuple[int, None]:
    """Reject an invitation."""
    invitation = await sync_to_async(InvitationService.retrieve_invitation)(
        payload.invitation_token
    )
    if invitation is None:
        return HTTPStatus.NO_CONTENT, None

    if invitation.state != Invitation.State.ACCEPTED and invitation.reject_time is None:
        invitation.reject_time = timezone.now()
        await invitation.asave(update_fields=["reject_time", "update_time"])

    return HTTPStatus.NO_CONTENT, None

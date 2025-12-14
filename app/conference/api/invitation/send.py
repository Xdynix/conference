from http import HTTPStatus
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from jinja2 import UndefinedError
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from pydantic import Field
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole
from app.conference.services import InvitationService
from app.conference.services.invitation import (
    InvitationEmailContext,
    SendInvitationResult,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error
from app.utils.email import EmailTemplate, RenderedEmail

from .core import router


class EmailTemplateRequest(EmailTemplate, Schema):
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)


class PreviewInvitationEmailRequest(EmailTemplateRequest):
    pass


class PreviewInvitationEmailResponse(RenderedEmail, Schema):
    pass


@router.post(
    "/conferences/{slug:conference_name}/invitations:preview-email",
    response={
        HTTPStatus.OK: PreviewInvitationEmailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Preview Invitation Email",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def preview_invitation_email(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,  # noqa: ARG001
    payload: PreviewInvitationEmailRequest,
) -> RenderedEmail:
    """Render an invitation email template with sample context.

    Returns a preview of the email that would be sent using the provided template. Uses
    sample context data including placeholder recipient information and sample
    accept/reject links.
    """
    sample_context = InvitationEmailContext.sample(
        invitation_accept_page_url=settings.INVITATION_ACCEPT_PAGE_URL,
        invitation_reject_page_url=settings.INVITATION_REJECT_PAGE_URL,
    )

    try:
        return payload.render(sample_context)
    except UndefinedError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


class SendInvitationsRequest(EmailTemplateRequest):
    invitation_uids: list[ULID] = Field(min_length=1, max_length=100)
    force_send_to_rejected: bool = False
    force_send_to_recent: bool = False


class SendInvitationsResponse(Schema):
    results: list[SendInvitationResult]


@router.post(
    "/conferences/{slug:conference_name}/invitations:send",
    response={
        HTTPStatus.OK: SendInvitationsResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Send Invitations",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def send_invitations(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: SendInvitationsRequest,
) -> dict[str, Any]:
    """Send invitation emails to the specified invitations.

    Validates that all provided invitation UIDs are visible to the current user. Any
    invitation that is not visible is treated as nonexistent, and the request returns
    422 without processing any invitations.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    visible_invitations = await InvitationService.visible_invitations(conference, user)
    visible_uids = {
        uid
        async for uid in visible_invitations.filter(
            uid__in=payload.invitation_uids
        ).values_list("uid", flat=True)
    }

    requested_uids = set(payload.invitation_uids)
    invisible_uids = requested_uids - visible_uids
    if invisible_uids:
        message = _("Some invitation UIDs do not exist: {uids}").format(
            uids=", ".join(str(uid) for uid in sorted(invisible_uids))
        )
        raise make_validation_error(
            path="invitation_uids",
            message=message,
        )

    results = await sync_to_async(InvitationService.send_invitations)(
        list(requested_uids),
        template=payload,
        invitation_accept_page_url=settings.INVITATION_ACCEPT_PAGE_URL,
        invitation_reject_page_url=settings.INVITATION_REJECT_PAGE_URL,
        force_send_to_rejected=payload.force_send_to_rejected,
        force_send_to_recent=payload.force_send_to_recent,
    )

    logger.info(
        "Invitations sent.",
        user=user,
        conference_name=conference.name,
        count=len(results),
    )

    return {"results": results}

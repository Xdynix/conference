from http import HTTPStatus
from typing import Any

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from jinja2 import UndefinedError
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from pydantic import EmailStr, Field
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole
from app.conference.services.review import (
    ReviewerNotificationContext,
    ReviewerNotificationService,
    SendNotificationResult,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse
from app.utils.email import EmailTemplate, RenderedEmail

from .core import router


class EmailTemplateRequest(EmailTemplate, Schema):
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)


class PreviewNotificationEmailRequest(EmailTemplateRequest):
    pass


class PreviewNotificationEmailResponse(RenderedEmail, Schema):
    pass


@router.post(
    "/conferences/{slug:conference_name}/reviewers:preview-notification-email",
    response={
        HTTPStatus.OK: PreviewNotificationEmailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Preview Reviewer Notification Email",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def preview_reviewer_notification_email(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,  # noqa: ARG001
    payload: PreviewNotificationEmailRequest,
) -> RenderedEmail:
    """Render a reviewer notification email template with sample context.

    Returns a preview of the email that would be sent using the provided template. Uses
    sample context data including placeholder recipient information.
    """
    sample_context = ReviewerNotificationContext.sample()

    try:
        return payload.render(sample_context)
    except UndefinedError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


class SendNotificationsRequest(EmailTemplateRequest):
    reviewers: list[ULID] = Field(min_length=1, max_length=100)
    reply_to: EmailStr | None = None
    force_send_to_recent: bool = False


class SendNotificationsResponse(Schema):
    results: list[SendNotificationResult]


@router.post(
    "/conferences/{slug:conference_name}/reviewers:send-notifications",
    response=SendNotificationsResponse,
    summary="Send Reviewer Notifications",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def send_reviewer_notifications(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: SendNotificationsRequest,
) -> dict[str, Any]:
    """Send notification emails to the specified reviewers.

    Each reviewer is processed independently; individual failures do not affect other
    reviewers in the batch.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    reviewer_uids = list(set(payload.reviewers))
    results = await sync_to_async(ReviewerNotificationService.send_notifications)(
        conference,
        reviewer_uids,
        template=payload,
        reply_to=payload.reply_to,
        force_send_to_recent=payload.force_send_to_recent,
    )

    logger.info(
        "Reviewer notifications sent.",
        user=user,
        conference_name=conference.name,
        count=len(results),
    )

    return {"results": results}

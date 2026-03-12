from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Status
from ninja.errors import HttpError

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, TrackRole
from app.conference.services import InvitationService, KeywordService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import DuplicateInvitation
from app.conference.types import InvitationTrackRole, KeywordText, Profile
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import (
    InvitationResponse,
    prefetch_invitation,
    router,
    validate_and_group_track_roles,
)


class CreateInvitationRequest(Profile):
    invitee_email: EmailStr
    desired_paper_count: int = Field(default=5, ge=0)
    interested_keywords: list[KeywordText] = Field(default_factory=list, max_length=100)
    conference_roles: list[ConferenceRole] = Field(default_factory=list, max_length=100)
    track_roles: list[InvitationTrackRole] = Field(default_factory=list, max_length=100)


@router.post(
    "/conferences/{slug:conference_name}/invitations",
    response={
        HTTPStatus.CREATED: InvitationResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Invitation",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def create_invitation(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateInvitationRequest,
) -> Status:
    """Create a conference invitation."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    try:
        keywords = await KeywordService.validate_keyword_texts(
            payload.interested_keywords
        )
    except ValueError as exc:
        raise make_validation_error(
            path="interested_keywords",
            message=str(exc),
        ) from exc

    try:
        track_roles_mapping = await validate_and_group_track_roles(payload.track_roles)
    except ValueError as exc:
        raise make_validation_error(path="track_roles", message=str(exc)) from exc

    try:
        invitation = await sync_to_async(InvitationService.create_invitation)(
            conference=conference,
            inviter=user,
            invitee_email=payload.invitee_email,
            given_name=payload.given_name,
            family_name=payload.family_name,
            affiliation=payload.affiliation,
            region_code=payload.region_code,
            desired_paper_count=payload.desired_paper_count,
            interested_keywords=keywords,
            conference_roles=payload.conference_roles,
            track_roles=track_roles_mapping,
        )
    except DuplicateInvitation as exc:
        message = _(
            "A pending invitation already exists for this conference and email."
        )
        raise HttpError(HTTPStatus.CONFLICT, message) from exc
    except ValueError as exc:
        raise make_validation_error(path="track_roles", message=str(exc)) from exc
    except InsufficientRolePermission as exc:
        raise HttpError(HTTPStatus.FORBIDDEN, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.INVITATION_CREATE,
        resource=invitation,
        scope=conference.name,
        payload=payload,
    )

    return Status(HTTPStatus.CREATED, await prefetch_invitation(invitation, request))

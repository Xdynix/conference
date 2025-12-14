from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import Field, PatchDict
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Invitation, TrackRole
from app.conference.services import InvitationService, KeywordService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import ImmutableInvitation
from app.conference.types import InvitationTrackRole, KeywordText, Profile
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import (
    InvitationResponse,
    prefetch_invitation,
    router,
    validate_and_group_track_roles,
)


class InvitationSchema(Profile):
    desired_paper_count: int = Field(ge=0)
    interested_keywords: list[KeywordText] = Field(max_length=100)
    conference_roles: list[ConferenceRole] = Field(max_length=100)
    track_roles: list[InvitationTrackRole] = Field(max_length=100)


@router.patch(
    "/conferences/{slug:conference_name}/invitations/{ulid:invitation_id}",
    response={
        HTTPStatus.OK: InvitationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update Invitation",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def update_invitation(
    request: AuthedHttpRequest,
    conference_name: str,
    invitation_id: ULID,
    payload: PatchDict[InvitationSchema],
) -> Invitation:
    """Update an invitation's profile data and/or roles."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    invitations = await InvitationService.visible_invitations(conference, user)
    is_visible = await invitations.filter(uid=invitation_id).aexists()
    if not is_visible:
        raise Http404

    try:
        keywords = await KeywordService.validate_keyword_texts(
            payload.get("interested_keywords")  # type: ignore[func-returns-value]
        )
    except ValueError as exc:
        raise make_validation_error(
            path="interested_keywords",
            message=str(exc),
        ) from exc

    track_roles_mapping = None
    if "track_roles" in payload:
        try:
            track_roles_mapping = await validate_and_group_track_roles(
                [
                    InvitationTrackRole(track=item["track"], role=item["role"])
                    for item in payload["track_roles"]
                ]
            )
        except ValueError as exc:
            raise make_validation_error(path="track_roles", message=str(exc)) from exc

    try:
        invitation = await sync_to_async(InvitationService.update_invitation)(
            invitation_uid=invitation_id,
            user=user,
            given_name=payload.get("given_name"),
            family_name=payload.get("family_name"),
            affiliation=payload.get("affiliation"),
            region_code=payload.get("region_code"),
            desired_paper_count=payload.get("desired_paper_count"),
            interested_keywords=keywords,
            conference_roles=payload.get("conference_roles"),
            track_roles=track_roles_mapping,
        )
    except ValueError as exc:
        raise make_validation_error(path="track_roles", message=str(exc)) from exc
    except ImmutableInvitation as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except InsufficientRolePermission as exc:
        raise HttpError(HTTPStatus.FORBIDDEN, str(exc)) from exc

    logger.info(
        "Invitation updated.",
        invitation_uid=invitation.uid,
        conference_name=conference.name,
        user_uid=user.uid,
    )

    return await prefetch_invitation(invitation)

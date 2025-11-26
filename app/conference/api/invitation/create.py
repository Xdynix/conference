from collections import defaultdict
from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    Track,
    TrackRole,
)
from app.conference.services import InvitationService, KeywordService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import DuplicateInvitation
from app.conference.types import KeywordText, Profile
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import InvitationResponse, router


class InvitationTrackRole(Schema):
    uid: ULID
    role: TrackRole


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
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
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
) -> tuple[int, Invitation]:
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

    track_uids = {track_role.uid for track_role in payload.track_roles}

    if track_uids:
        tracks = [
            track async for track in Track.objects.active().filter(uid__in=track_uids)
        ]
        track_objs = {track.uid: track for track in tracks}

        missing_uids = track_uids - set(track_objs)
        if missing_uids:
            message = _("Invalid track UID(s): {uids}").format(
                uids=", ".join(sorted(str(uid) for uid in missing_uids))
            )
            raise make_validation_error(path="track_roles", message=message)
    else:
        track_objs = {}

    track_roles_mapping = defaultdict(list)
    for track_role in payload.track_roles:
        track = track_objs[track_role.uid]
        track_roles_mapping[track].append(track_role.role)

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

    logger.info(
        "Invitation created.",
        invitation=invitation,
        conference=conference,
        inviter=user,
    )

    invitation = await Invitation.objects.prefetch_related(
        "interested_keywords",
        "conference_role_entries",
        "track_role_entries__track",
    ).aget(pk=invitation.pk)
    return HTTPStatus.CREATED, invitation

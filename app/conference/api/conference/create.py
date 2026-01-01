from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Schema
from ninja.errors import HttpError

from app.conference.models import (
    Conference,
    ConferenceVisibility,
    TrackVisibility,
)
from app.conference.services import ConferenceService, KeywordService
from app.conference.services.conference import ConferenceNameConflict, TrackData
from app.conference.types import Conference as ConferenceSchema
from app.conference.types import KeywordSetName, KeywordText, TrackDisplayName
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import ConferenceDetailResponse, prefetch_conference, router


class CreateTrackPayload(Schema):
    display_name: TrackDisplayName
    visibility: TrackVisibility = TrackVisibility.ADMIN_ONLY


class CreateConferenceRequest(ConferenceSchema):
    keywords: list[KeywordText] = Field(default_factory=list, max_length=500)
    keyword_sets: list[KeywordSetName] = Field(default_factory=list, max_length=50)
    visibility: ConferenceVisibility = ConferenceVisibility.ADMIN_ONLY
    registration_enabled: bool = False
    tracks: list[CreateTrackPayload] = Field(default_factory=list, max_length=100)  # type: ignore[assignment]


@router.post(
    "/conferences",
    response={
        HTTPStatus.CREATED: ConferenceDetailResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Conference",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def create_conference(
    request: AuthedHttpRequest,
    payload: CreateConferenceRequest,
) -> tuple[int, Conference]:
    """Create a conference."""
    try:
        keywords = await KeywordService.validate_keyword_texts(payload.keywords)
    except ValueError as exc:
        raise make_validation_error(path="keywords", message=str(exc)) from exc

    try:
        keyword_sets = await KeywordService.validate_keyword_set_names(
            payload.keyword_sets
        )
    except ValueError as exc:
        raise make_validation_error(path="keyword_sets", message=str(exc)) from exc

    try:
        conference = await sync_to_async(ConferenceService.create_conference)(
            name=payload.name,
            display_name=payload.display_name,
            visibility=payload.visibility,
            registration_enabled=payload.registration_enabled,
            keywords=keywords,
            keyword_sets=keyword_sets,
            tracks=[
                TrackData(display_name=track.display_name, visibility=track.visibility)
                for track in payload.tracks
            ],
        )
    except ConferenceNameConflict as exc:
        message = _("A conference with that name already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    user = await request.auser()
    logger.info(
        "Conference created.",
        conference_name=conference.name,
        user_uid=user.uid,
    )

    return HTTPStatus.CREATED, await prefetch_conference(conference, user)

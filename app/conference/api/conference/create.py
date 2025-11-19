from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Schema
from ninja.errors import HttpError

from app.conference.models import Conference, Keyword, Track
from app.conference.types import (
    ConferenceDetail,
    ConferenceDisplayName,
    ConferenceName,
    KeywordSetName,
    TrackDisplayName,
)
from app.conference.types import Keyword as KeywordText
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import prefetch_tracks, router, validate_keyword_payload


class TrackSchema(Schema):
    display_name: TrackDisplayName
    visibility: Track.Visibility = Track.Visibility.ADMIN_ONLY


class CreateConferenceRequest(Schema):
    name: ConferenceName
    display_name: ConferenceDisplayName
    keywords: list[KeywordText] = Field(default_factory=list)
    keyword_sets: list[KeywordSetName] = Field(default_factory=list)
    visibility: Conference.Visibility = Conference.Visibility.ADMIN_ONLY
    tracks: list[TrackSchema] = Field(default_factory=list)


@transaction.atomic
def create_new_conference(payload: CreateConferenceRequest) -> Conference:
    keywords, keyword_sets = validate_keyword_payload(
        keyword_texts=payload.keywords,
        keyword_set_names=payload.keyword_sets,
    )

    try:
        conference = Conference.objects.create(
            name=payload.name,
            display_name=payload.display_name,
            visibility=payload.visibility,
        )
    except IntegrityError as exc:
        message = _("A conference with that name already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    assigned_keywords: set[Keyword] = set()
    assigned_keywords.update(keywords)
    for keyword_set in keyword_sets:
        assigned_keywords.update(keyword_set.keywords.all())
    if assigned_keywords:
        conference.keywords.set(assigned_keywords)

    tracks: list[Track] = [
        Track(
            conference=conference,
            display_name=provided_track.display_name,
            ordering=idx,
            visibility=provided_track.visibility,
        )
        for idx, provided_track in enumerate(payload.tracks)
    ]
    if tracks:
        Track.objects.bulk_create(tracks)

    return conference


@router.post(
    "/conferences",
    response={
        HTTPStatus.CREATED: ConferenceDetail,
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
    conference = await sync_to_async(create_new_conference)(payload)

    user = await request.auser()
    logger.info("Conference created.", conference=conference, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=conference.pk
    )
    await prefetch_tracks(conference, user=user)
    return HTTPStatus.CREATED, conference

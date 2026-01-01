from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from loguru import logger
from ninja import PatchDict, Schema
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Track, TrackVisibility
from app.conference.services import TrackService
from app.conference.types import TrackDisplayName
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import ConferenceDetailResponse, prefetch_conference, router


class CreateTrackRequest(Schema):
    display_name: TrackDisplayName
    visibility: TrackVisibility = TrackVisibility.ADMIN_ONLY


@router.post(
    "/conferences/{slug:conference_name}/tracks",
    response={HTTPStatus.CREATED: ConferenceDetailResponse},
    summary="Create Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def create_track(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateTrackRequest,
) -> tuple[int, Conference]:
    """Create a track for a conference."""
    try:
        track = await sync_to_async(TrackService.create_track)(
            conference_name=conference_name,
            display_name=payload.display_name,
            visibility=payload.visibility,
        )
    except Conference.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    conference = track.conference

    logger.info(
        "Track created.",
        conference_name=conference.name,
        track_uid=track.uid,
        user_uid=user.uid,
    )

    return HTTPStatus.CREATED, await prefetch_conference(conference, user)


class TrackSchema(Schema):
    display_name: TrackDisplayName
    visibility: TrackVisibility
    submissions_enabled: bool


@router.patch(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_uid}",
    response=ConferenceDetailResponse,
    summary="Update Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_track(
    request: AuthedHttpRequest,
    conference_name: str,
    track_uid: ULID,
    payload: PatchDict[TrackSchema],
) -> Conference:
    """Update a track for a conference."""
    try:
        track = await TrackService.update_track(
            conference_name=conference_name,
            track_uid=track_uid,
            **payload,
        )
    except Track.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    conference = track.conference

    logger.info(
        "Track updated.",
        conference_name=conference.name,
        track_uid=track.uid,
        user_uid=user.uid,
    )

    return await prefetch_conference(conference, user)


@router.delete(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_uid}",
    response=ConferenceDetailResponse,
    summary="Delete Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def delete_track(
    request: AuthedHttpRequest,
    conference_name: str,
    track_uid: ULID,
) -> Conference:
    """Delete a track for a conference."""
    try:
        track = await sync_to_async(TrackService.deactivate_track)(
            conference_name=conference_name,
            track_uid=track_uid,
        )
    except Track.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    conference = track.conference

    logger.info(
        "Track deleted.",
        conference_name=conference.name,
        track_uid=track.uid,
        user_uid=user.uid,
    )

    return await prefetch_conference(conference, user)


class MoveTrackRequest(Schema):
    after_track: ULID | None = None


@router.post(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_uid}:move",
    response={
        HTTPStatus.OK: ConferenceDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Move Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def move_track(
    request: AuthedHttpRequest,
    conference_name: str,
    track_uid: ULID,
    payload: MoveTrackRequest,
) -> Conference:
    """Reorder a track within the conference.

    Places the track after a specified target track, or at the beginning if no target
    is provided.
    """
    try:
        track = await sync_to_async(TrackService.move_track)(
            conference_name=conference_name,
            track_uid=track_uid,
            after_track_uid=payload.after_track,
        )
    except (Conference.DoesNotExist, Track.DoesNotExist) as exc:
        raise Http404 from exc
    except ValueError as exc:
        raise make_validation_error(path="after_track", message=str(exc)) from exc

    user = await request.auser()
    conference = track.conference

    logger.info(
        "Track moved.",
        conference_name=conference.name,
        track_uid=track.uid,
        user_uid=user.uid,
    )

    return await prefetch_conference(conference, user)

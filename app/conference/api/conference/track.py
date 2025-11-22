from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from loguru import logger
from ninja import PatchDict, Schema
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Track
from app.conference.services import TrackService
from app.conference.types import TrackDisplayName
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import ConferenceDetailResponse, prefetch_conference, router


class CreateTrackRequest(Schema):
    display_name: TrackDisplayName
    visibility: Track.Visibility = Track.Visibility.ADMIN_ONLY


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

    logger.info("Track created.", conference=conference, track=track, user=user)

    return HTTPStatus.CREATED, await prefetch_conference(conference, user)


# Separate from CreateTrackRequest: PATCH requires no defaults on omitted fields.
class TrackSchema(Schema):
    display_name: TrackDisplayName
    visibility: Track.Visibility


@router.patch(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}",
    response=ConferenceDetailResponse,
    summary="Update Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_track(
    request: AuthedHttpRequest,
    conference_name: str,
    track_id: ULID,
    payload: PatchDict[TrackSchema],
) -> Conference:
    """Update a track for a conference."""
    try:
        track = await TrackService.update_track(
            conference_name=conference_name,
            track_uid=track_id,
            **payload,
        )
    except Track.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    conference = track.conference

    logger.info("Track updated.", conference=conference, track=track, user=user)

    return await prefetch_conference(conference, user)


@router.delete(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}",
    response=ConferenceDetailResponse,
    summary="Delete Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def delete_track(
    request: AuthedHttpRequest,
    conference_name: str,
    track_id: ULID,
) -> Conference:
    """Delete a track for a conference."""
    try:
        track = await sync_to_async(TrackService.deactivate_track)(
            conference_name=conference_name,
            track_uid=track_id,
        )
    except Track.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    conference = track.conference

    logger.info("Track deleted.", conference=conference, track=track, user=user)

    return await prefetch_conference(conference, user)


class MoveTrackRequest(Schema):
    after_track: ULID | None = None


@router.post(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}:move",
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
    track_id: ULID,
    payload: MoveTrackRequest,
) -> Conference:
    """Reorder a track within the conference.

    Places the track after a specified target track, or at the beginning if no target
    is provided.
    """
    try:
        track = await sync_to_async(TrackService.move_track)(
            conference_name=conference_name,
            track_uid=track_id,
            after_track_uid=payload.after_track,
        )
    except (Conference.DoesNotExist, Track.DoesNotExist) as exc:
        raise Http404 from exc
    except ValueError as exc:
        raise make_validation_error(path="after_track", message=str(exc)) from exc

    user = await request.auser()
    conference = track.conference

    logger.info("Track moved.", conference=conference, track=track, user=user)

    return await prefetch_conference(conference, user)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from ninja import PatchDict, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Track, TrackVisibility
from app.conference.services import TrackService
from app.conference.types import TrackDisplayName
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

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

    conference = track.conference

    await audit(
        request=request,
        action=AuditAction.TRACK_CREATE,
        resource=track,
        scope=conference.name,
        payload=payload,
    )

    user = await request.auser()
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

    conference = track.conference

    await audit(
        request=request,
        action=AuditAction.TRACK_UPDATE,
        resource=track,
        scope=conference.name,
        payload=payload,
    )

    user = await request.auser()
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

    conference = track.conference

    await audit(
        request=request,
        action=AuditAction.TRACK_DELETE,
        resource=track,
        scope=conference.name,
    )

    user = await request.auser()
    return await prefetch_conference(conference, user)


@router.post(
    "/conferences/{slug:conference_name}/tracks:reorder",
    response={
        HTTPStatus.OK: ConferenceDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Reorder Tracks",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def reorder_tracks(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: list[ULID],
) -> Conference:
    """Reorder tracks by providing the complete list of UIDs in desired order.

    All active tracks for the conference must be included exactly once.
    """
    try:
        conference = await sync_to_async(TrackService.reorder_tracks)(
            conference_name=conference_name,
            track_uids=payload,
        )
    except Conference.DoesNotExist as exc:
        raise Http404 from exc
    except ValueError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message=str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.TRACK_REORDER,
        resource=AuditResource.TRACK,
        scope=conference.name,
        payload={"track_uids": [str(uid) for uid in payload]},
    )

    user = await request.auser()
    return await prefetch_conference(conference, user)

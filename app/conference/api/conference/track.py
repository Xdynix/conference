from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import aget_object_or_404, get_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import PatchDict, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Track
from app.conference.services import ConferenceService
from app.conference.types import ConferenceDetail, TrackDisplayName
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import router
from .create import TrackSchema as CreateTrackSchema


@transaction.atomic
def create_new_track(
    *,
    conference_name: str,
    payload: CreateTrackSchema,
) -> tuple[Conference, Track]:
    # Lock the conference row to prevent race conditions when calculating the next
    # ordering value, even though we don't update the conference itself.
    conference = get_object_or_404(
        Conference.objects.select_for_update().filter(active=True),
        name=conference_name,
    )
    last_ordering = (
        conference.tracks.order_by("-ordering")
        .values_list("ordering", flat=True)
        .first()
    )
    next_ordering = 0 if last_ordering is None else last_ordering + 1
    track = Track.objects.create(
        conference=conference,
        display_name=payload.display_name,
        ordering=next_ordering,
        visibility=payload.visibility,
    )
    return conference, track


@router.post(
    "/conferences/{slug:conference_name}/tracks",
    response={HTTPStatus.CREATED: ConferenceDetail},
    summary="Create Track",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def create_track(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateTrackSchema,
) -> tuple[int, Conference]:
    """Create a track for a conference."""
    conference, track = await sync_to_async(create_new_track)(
        conference_name=conference_name,
        payload=payload,
    )

    user = await request.auser()
    logger.info("Track created.", conference=conference, track=track, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=conference.pk,
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return HTTPStatus.CREATED, conference


class TrackSchema(Schema):
    display_name: TrackDisplayName
    visibility: Track.Visibility


@router.patch(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}",
    response=ConferenceDetail,
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
    user = await request.auser()

    track = await aget_object_or_404(
        Track.objects.select_related("conference").filter(
            conference__name=conference_name,
            conference__active=True,
            active=True,
        ),
        uid=track_id,
    )
    if payload:
        for attr, value in payload.items():
            setattr(track, attr, value)
        await track.asave(update_fields=[*payload.keys(), "update_time"])

        logger.info("Track updated.", track=track, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=track.conference_id
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return conference


@transaction.atomic
def deactivate_track(*, conference_name: str, track_id: ULID) -> Track:
    track = get_object_or_404(
        Track.objects.select_for_update()
        .select_related("conference")
        .filter(
            conference__name=conference_name,
            conference__active=True,
            active=True,
        ),
        uid=track_id,
    )
    track.active = False
    track.save(update_fields=["active", "update_time"])
    return track


@router.delete(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}",
    response=ConferenceDetail,
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
    track = await sync_to_async(deactivate_track)(
        conference_name=conference_name,
        track_id=track_id,
    )

    user = await request.auser()
    logger.info("Track deleted.", track=track, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=track.conference_id
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return conference


class MoveTrackRequest(Schema):
    after_track: ULID | None = None


@transaction.atomic
def move_track_ordering(
    *,
    conference_name: str,
    track_uid: ULID,
    after_track_uid: ULID | None,
) -> Conference:
    conference = get_object_or_404(
        Conference.objects.select_for_update().filter(active=True),
        name=conference_name,
    )
    track = get_object_or_404(
        conference.tracks.filter(active=True),
        uid=track_uid,
    )

    after_track: Track | None = None
    if after_track_uid is not None:
        if after_track_uid == track_uid:
            message = _("Track cannot be moved after itself.")
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

        after_track = conference.tracks.filter(uid=after_track_uid, active=True).first()
        if after_track is None:
            message = _("Target track does not exist.")
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    # Include inactive tracks in reordering to maintain consistent ordering values
    # across the entire track history. This simplifies the logic and preserves ordering
    # continuity if tracks are reactivated later.
    conference_tracks = list(conference.tracks.exclude(pk=track.pk))
    if after_track is None:
        conference_tracks.insert(0, track)
    else:
        try:
            target_index = next(
                idx
                for idx, track_obj in enumerate(conference_tracks)
                if track_obj == after_track
            )
        except StopIteration as exc:  # pragma: no cover
            # Handle very rare edge case where target track was hard-deleted from
            # database after validation but before fetching `conference_tracks` list.
            message = _("Target track does not exist.")
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message) from exc
        conference_tracks.insert(target_index + 1, track)

    for ordering, track_obj in enumerate(conference_tracks):
        if track_obj.ordering != ordering:
            track_obj.ordering = ordering
            track_obj.save(update_fields=["ordering", "update_time"])

    return conference


@router.post(
    "/conferences/{slug:conference_name}/tracks/{ulid:track_id}:move",
    response={
        HTTPStatus.OK: ConferenceDetail,
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
    """Reorder tracks within a conference."""
    conference = await sync_to_async(move_track_ordering)(
        conference_name=conference_name,
        track_uid=track_id,
        after_track_uid=payload.after_track,
    )

    user = await request.auser()
    logger.info("Track moved.", conference=conference, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=conference.pk
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return conference

from http import HTTPStatus
from typing import Annotated

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, PatchDict, Router, Schema
from ninja.errors import HttpError
from pydantic import AwareDatetime, BeforeValidator, StringConstraints
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import CodePool, Conference, ConferenceRole, Track
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.infra.models import Mutex
from app.utils.sanitization import sanitize_text

router = Router(tags=["Code Pool"], exclude_none=True)

code_pool_meta = CodePool._meta
code_pool_name_field = code_pool_meta.get_field("name")
code_pool_prefix_field = code_pool_meta.get_field("prefix")

CodePoolName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=code_pool_name_field.max_length,
        strip_whitespace=True,
    ),
]
CodePoolPrefix = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        pattern=r"^[-a-zA-Z0-9_]+$",  # django.core.validators.slug_re
        min_length=1,
        max_length=code_pool_prefix_field.max_length,
        strip_whitespace=True,
    ),
    Field(
        description=str(code_pool_prefix_field.help_text),
        examples=["CBPK-2"],
    ),
]


class CodePoolResponse(Schema):
    uid: ULID
    name: CodePoolName
    prefix: CodePoolPrefix
    next_sequence: int
    create_time: AwareDatetime
    update_time: AwareDatetime


@router.get(
    "/conferences/{slug:conference_name}/code-pools",
    response=list[CodePoolResponse],
    summary="List Code Pools",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def list_code_pools(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> list[CodePool]:
    """Return all code pools for the conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return [pool async for pool in conference.code_pools.order_by("prefix")]


class CreateCodePoolRequest(Schema):
    name: CodePoolName
    prefix: CodePoolPrefix


@router.post(
    "/conferences/{slug:conference_name}/code-pools",
    response={HTTPStatus.CREATED: CodePoolResponse},
    summary="Create Code Pool",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def create_code_pool(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateCodePoolRequest,
) -> tuple[int, CodePool]:
    """Create a new code pool for the conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    try:
        pool = await CodePool.objects.acreate(
            conference=conference,
            name=payload.name,
            prefix=payload.prefix,
        )
    except IntegrityError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("A code pool with this prefix already exists for this conference."),
        ) from exc

    user = await request.auser()
    logger.info(
        "Code pool created.",
        code_pool_uid=pool.uid,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return HTTPStatus.CREATED, pool


class CodePoolSchema(Schema):
    name: CodePoolName
    prefix: CodePoolPrefix


@router.patch(
    "/conferences/{slug:conference_name}/code-pools/{ulid:code_pool_id}",
    response=CodePoolResponse,
    summary="Update Code Pool",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_code_pool(
    request: AuthedHttpRequest,
    conference_name: str,
    code_pool_id: ULID,
    payload: PatchDict[CodePoolSchema],
) -> CodePool:
    """Update a code pool's name or prefix."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    pool = await aget_object_or_404(
        CodePool.objects.filter(conference=conference),
        uid=code_pool_id,
    )

    update_fields: list[str] = []
    for attr, value in payload.items():
        setattr(pool, attr, value)
        update_fields.append(attr)

    if update_fields:
        try:
            await pool.asave(update_fields=[*update_fields, "update_time"])
        except IntegrityError as exc:
            raise HttpError(
                HTTPStatus.CONFLICT,
                _("A code pool with this prefix already exists for this conference."),
            ) from exc

    user = await request.auser()
    logger.info(
        "Code pool updated.",
        code_pool_uid=pool.uid,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return pool


@router.delete(
    "/conferences/{slug:conference_name}/code-pools/{ulid:code_pool_id}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Code Pool",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def delete_code_pool(
    request: AuthedHttpRequest,
    conference_name: str,
    code_pool_id: ULID,
) -> tuple[HTTPStatus, None]:
    """Delete a code pool.

    Fails if any tracks are still referencing this pool.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    pool = await aget_object_or_404(
        CodePool.objects.filter(conference=conference),
        uid=code_pool_id,
    )

    try:
        await pool.adelete()
    except ProtectedError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("Cannot delete code pool: it is still referenced by one or more tracks."),
        ) from exc

    user = await request.auser()
    logger.info(
        "Code pool deleted.",
        code_pool_uid=code_pool_id,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return HTTPStatus.NO_CONTENT, None


class TrackCodePoolAssignment(Schema):
    track_uid: ULID = Field(validation_alias="uid")
    code_pool_uid: ULID | None

    @staticmethod
    def resolve_code_pool_uid(track: Track) -> ULID | None:
        return track.code_pool.uid if track.code_pool else None


@router.get(
    "/conferences/{slug:conference_name}/tracks/code-pool-assignments",
    response=list[TrackCodePoolAssignment],
    summary="Get Track Code Pool Assignments",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def get_track_code_pool_assignments(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> list[Track]:
    """Return all tracks with their code pool assignments."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return [
        track async for track in conference.tracks.active().select_related("code_pool")
    ]


class TrackCodePoolAssignmentEntry(Schema):
    track_uid: ULID
    code_pool_uid: ULID | None


def update_track_assignments(
    conference: Conference,
    entries: list[TrackCodePoolAssignmentEntry],
) -> list[Track]:
    """Update track code pool assignments in a single transaction."""
    with Mutex.lock_in_transaction(
        str(conference.pk),
        namespace="track_code_pool_assignments",
    ):
        tracks = {
            track.uid: track
            for track in conference.tracks.active().select_related("code_pool")
        }
        pools = {pool.uid: pool for pool in conference.code_pools.all()}

        entry_track_uids = {entry.track_uid for entry in entries}
        missing_tracks = set(tracks.keys()) - entry_track_uids
        if missing_tracks:
            missing_names = [tracks[uid].display_name for uid in missing_tracks]
            raise ValueError(
                _("Missing tracks in payload: {names}.").format(
                    names=", ".join(sorted(missing_names))
                )
            )

        invalid_track_uids = entry_track_uids - set(tracks.keys())
        if invalid_track_uids:
            raise ValueError(
                _("Invalid track UIDs: {uids}.").format(
                    uids=", ".join(str(uid) for uid in sorted(invalid_track_uids))
                )
            )

        invalid_pool_uids = {
            entry.code_pool_uid
            for entry in entries
            if entry.code_pool_uid and entry.code_pool_uid not in pools
        }
        if invalid_pool_uids:
            raise ValueError(
                _("Invalid code pool UIDs: {uids}.").format(
                    uids=", ".join(str(uid) for uid in invalid_pool_uids)
                )
            )

        for entry in entries:
            track = tracks[entry.track_uid]
            new_pool = pools.get(entry.code_pool_uid) if entry.code_pool_uid else None
            if track.code_pool != new_pool:
                track.code_pool = new_pool
                track.save(update_fields=["code_pool", "update_time"])

        return list(tracks.values())


@router.put(
    "/conferences/{slug:conference_name}/tracks/code-pool-assignments",
    response=list[TrackCodePoolAssignment],
    summary="Update Track Code Pool Assignments",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_track_code_pool_assignments(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: list[TrackCodePoolAssignmentEntry],
) -> list[Track]:
    """Update code pool assignments for all tracks.

    All conference tracks must be included in the payload.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    duplicate_track_uids: set[ULID] = set()
    seen_track_uids: set[ULID] = set()
    for entry in payload:
        if entry.track_uid in seen_track_uids:
            duplicate_track_uids.add(entry.track_uid)
        else:
            seen_track_uids.add(entry.track_uid)
    if duplicate_track_uids:
        message = _("Duplicate track UIDs in payload: {uids}.").format(
            uids=", ".join(str(uid) for uid in sorted(duplicate_track_uids))
        )
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    try:
        tracks = await sync_to_async(update_track_assignments)(conference, payload)
    except ValueError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    user = await request.auser()
    logger.info(
        "Track code pool assignments updated.",
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return tracks

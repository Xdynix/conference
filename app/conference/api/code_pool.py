from http import HTTPStatus
from typing import Annotated

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
from app.conference.models import CodePool, Conference, ConferenceRole
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
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

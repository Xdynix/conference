from http import HTTPStatus
from typing import Annotated

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import PatchDict, Router, Schema
from ninja.errors import HttpError
from pydantic import BeforeValidator, StringConstraints
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import AttendanceType, Conference, ConferenceRole
from app.conference.services import ConferenceService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.utils.sanitization import sanitize_text

router = Router(tags=["Attendance Type"], exclude_none=True)


attendance_type_meta = AttendanceType._meta
attendance_type_display_name_field = attendance_type_meta.get_field("display_name")

AttendanceTypeDisplayName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=attendance_type_display_name_field.max_length,
        strip_whitespace=True,
    ),
]


class AttendanceTypeResponse(Schema):
    uid: ULID
    display_name: AttendanceTypeDisplayName
    admin_only: bool
    paper_required: bool


@router.get(
    "/conferences/{slug:conference_name}/attendance-types",
    response=list[AttendanceTypeResponse],
    summary="List Attendance Types",
    auth=is_authenticated,
)
async def list_attendance_types(
    request: AuthedHttpRequest,
    conference_name: str,
) -> list[AttendanceType]:
    """Lists attendance types available for registration.

    Returns all attendance types for admins. For regular users, returns only
    non-admin-only types when registration is enabled, or an empty list when
    registration is disabled.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    return [
        attendance_type
        async for attendance_type in await ConferenceService.visible_attendance_types(
            user, conference
        )
    ]


class CreateAttendanceTypeRequest(Schema):
    display_name: AttendanceTypeDisplayName
    admin_only: bool = True
    paper_required: bool = True


@router.post(
    "/conferences/{slug:conference_name}/attendance-types",
    response={HTTPStatus.CREATED: AttendanceTypeResponse},
    summary="Create Attendance Type",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def create_attendance_type(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateAttendanceTypeRequest,
) -> tuple[int, AttendanceType]:
    """Create a new attendance type for the conference.

    The new type is appended to the end of the ordering.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    last_ordering = await (
        conference.attendance_types.order_by("-ordering")
        .values_list("ordering", flat=True)
        .afirst()
    )
    next_ordering = 0 if last_ordering is None else last_ordering + 1

    try:
        attendance_type = await AttendanceType.objects.acreate(
            conference=conference,
            display_name=payload.display_name,
            ordering=next_ordering,
            admin_only=payload.admin_only,
            paper_required=payload.paper_required,
        )
    except IntegrityError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("An attendance type with this name already exists for this conference."),
        ) from exc

    user = await request.auser()
    logger.info(
        "Attendance type created.",
        attendance_type_uid=attendance_type.uid,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return HTTPStatus.CREATED, attendance_type


class AttendanceTypeSchema(Schema):
    display_name: AttendanceTypeDisplayName
    admin_only: bool
    paper_required: bool


@router.patch(
    "/conferences/{slug:conference_name}/attendance-types/{ulid:attendance_type_uid}",
    response=AttendanceTypeResponse,
    summary="Update Attendance Type",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_attendance_type(
    request: AuthedHttpRequest,
    conference_name: str,
    attendance_type_uid: ULID,
    payload: PatchDict[AttendanceTypeSchema],
) -> AttendanceType:
    """Update an attendance type's display name, visibility, or paper requirement."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    attendance_type = await aget_object_or_404(
        AttendanceType.objects.filter(conference=conference),
        uid=attendance_type_uid,
    )

    update_fields: list[str] = []
    for attr, value in payload.items():
        setattr(attendance_type, attr, value)
        update_fields.append(attr)

    if update_fields:
        try:
            await attendance_type.asave(update_fields=update_fields)
        except IntegrityError as exc:
            raise HttpError(
                HTTPStatus.CONFLICT,
                _(
                    "An attendance type with this name already exists for this "
                    "conference."
                ),
            ) from exc

    user = await request.auser()
    logger.info(
        "Attendance type updated.",
        attendance_type_uid=attendance_type.uid,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return attendance_type


@router.delete(
    "/conferences/{slug:conference_name}/attendance-types/{ulid:attendance_type_uid}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Attendance Type",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def delete_attendance_type(
    request: AuthedHttpRequest,
    conference_name: str,
    attendance_type_uid: ULID,
) -> tuple[HTTPStatus, None]:
    """Delete an attendance type.

    Fails if any registrations are still referencing this type.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    attendance_type = await aget_object_or_404(
        AttendanceType.objects.filter(conference=conference),
        uid=attendance_type_uid,
    )

    try:
        await attendance_type.adelete()
    except ProtectedError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _(
                "Cannot delete attendance type: it is still referenced by one or "
                "more registrations."
            ),
        ) from exc

    user = await request.auser()
    logger.info(
        "Attendance type deleted.",
        attendance_type_uid=attendance_type_uid,
        conference_name=conference.name,
        actor_uid=user.uid,
    )

    return HTTPStatus.NO_CONTENT, None

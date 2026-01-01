from typing import Annotated

from django.shortcuts import aget_object_or_404
from ninja import Router, Schema
from pydantic import BeforeValidator, StringConstraints
from ulid import ULID

from app.conference.models import AttendanceType
from app.conference.services import ConferenceService
from app.core.auth import is_authenticated
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

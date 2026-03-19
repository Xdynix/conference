# Note: These endpoints do not use Mutex for simplicity. Concurrent operations may
# result in slightly inconsistent ordering (e.g., gaps or duplicates in ordering
# values). This is acceptable for these low-frequency admin operations; the secondary
# sort by `display_name` ensures deterministic results.

from http import HTTPStatus

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import PatchDict, Schema, Status
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.conference.auth import has_any_conference_roles
from app.conference.models import AttendanceType, Conference, ConferenceRole
from app.conference.services import ConferenceService
from app.conference.types import AttendanceType as AttendanceTypeResponse
from app.conference.types import AttendanceTypeDisplayName
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


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
) -> Status[AttendanceType]:
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
        is_conflict = await AttendanceType.objects.filter(
            conference=conference,
            display_name=payload.display_name,
        ).aexists()
        if not is_conflict:  # pragma: no cover
            raise
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("An attendance type with this name already exists for this conference."),
        ) from exc

    await audit(
        request=request,
        action=AuditAction.ATTENDANCE_TYPE_CREATE,
        resource=attendance_type,
        scope=conference.name,
        payload=payload,
    )

    return Status(HTTPStatus.CREATED, attendance_type)


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
            is_conflict = await (
                AttendanceType.objects.filter(
                    conference=conference,
                    display_name=attendance_type.display_name,
                )
                .exclude(pk=attendance_type.pk)
                .aexists()
            )
            if not is_conflict:  # pragma: no cover
                raise
            raise HttpError(
                HTTPStatus.CONFLICT,
                _(
                    "An attendance type with this name already exists for this "
                    "conference."
                ),
            ) from exc

    await audit(
        request=request,
        action=AuditAction.ATTENDANCE_TYPE_UPDATE,
        resource=attendance_type,
        scope=conference.name,
        payload=payload,
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
) -> Status[None]:
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

    await audit(
        request=request,
        action=AuditAction.ATTENDANCE_TYPE_DELETE,
        resource=attendance_type,
        scope=conference.name,
    )

    return Status(HTTPStatus.NO_CONTENT, None)


@router.post(
    "/conferences/{slug:conference_name}/attendance-types:reorder",
    response=list[AttendanceTypeResponse],
    summary="Reorder Attendance Types",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def reorder_attendance_types(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: list[ULID],
) -> list[AttendanceType]:
    """Reorder attendance types by providing the complete list of UIDs in desired order.

    All attendance types for the conference must be included exactly once.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    if len(payload) != len(set(payload)):
        seen: set[ULID] = set()
        duplicates: set[ULID] = set()
        for uid in payload:
            if uid in seen:
                duplicates.add(uid)
            seen.add(uid)
        raise HttpError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            _("Duplicate UIDs in payload: {uids}.").format(
                uids=", ".join(str(uid) for uid in sorted(duplicates))
            ),
        )

    existing_types = {at.uid: at async for at in conference.attendance_types.all()}
    existing_uids = set(existing_types)
    payload_uids = set(payload)

    missing_uids = existing_uids - payload_uids
    if missing_uids:
        raise HttpError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            _("Missing UIDs in payload: {uids}.").format(
                uids=", ".join(str(uid) for uid in sorted(missing_uids))
            ),
        )

    invalid_uids = payload_uids - existing_uids
    if invalid_uids:
        raise HttpError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            _("Invalid UIDs: {uids}.").format(
                uids=", ".join(str(uid) for uid in sorted(invalid_uids))
            ),
        )

    for ordering, uid in enumerate(payload):
        attendance_type = existing_types[uid]
        if attendance_type.ordering != ordering:
            attendance_type.ordering = ordering
            await attendance_type.asave(update_fields=["ordering"])

    await audit(
        request=request,
        action=AuditAction.ATTENDANCE_TYPE_REORDER,
        resource=AuditResource.ATTENDANCE_TYPE,
        scope=conference.name,
        payload={"uids": [str(uid) for uid in payload]},
    )

    return [existing_types[uid] for uid in payload]

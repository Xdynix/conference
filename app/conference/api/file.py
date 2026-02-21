from functools import partial
from http import HTTPStatus
from typing import cast

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from pydantic import AwareDatetime

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceFile, ConferenceRole
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.infra.models import Mutex
from app.utils.files import (
    UploadValidationError,
    build_file_download_response,
    validate_upload,
)
from app.utils.sanitization import sanitize_filename

router = Router(tags=["Conference File"], exclude_none=True)


class ConferenceFileResponse(Schema):
    name: str
    filename: str
    size: int
    create_time: AwareDatetime
    update_time: AwareDatetime

    @staticmethod
    def resolve_size(conference_file: ConferenceFile) -> int:
        return cast(int, conference_file.file.size)


@router.get(
    "/conferences/{slug:conference_name}/files",
    response=list[ConferenceFileResponse],
    summary="List Conference Files",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def list_conference_files(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> list[ConferenceFile]:
    """List shared conference files (instructions, forms, etc.)."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return [file async for file in conference.files.order_by("name")]


@router.get(
    "/conferences/{slug:conference_name}/files/{slug:conference_file_name}",
    openapi_extra={
        "responses": {
            200: {
                "content": {
                    "application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"},
                    },
                },
            }
        }
    },
    summary="Download Conference File",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def download_conference_file(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    conference_file_name: str,
) -> HttpResponse | StreamingHttpResponse:
    """Download a shared conference file by name."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    conference_file = await aget_object_or_404(
        conference.files,
        name=conference_file_name,
    )
    try:
        return build_file_download_response(
            conference_file.file,
            filename=conference_file.filename,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise Http404 from exc


@router.post(
    "/conferences/{slug:conference_name}/files/{slug:conference_file_name}:upload",
    response={
        HTTPStatus.CREATED: ConferenceFileResponse,
        HTTPStatus.OK: ConferenceFileResponse,
    },
    summary="Upload Conference File",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def upload_conference_file(
    request: AuthedHttpRequest,
    conference_name: str,
    conference_file_name: str,
    file: File[UploadedFile],
) -> tuple[int, ConferenceFile]:
    """Create or replace a shared conference file."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    try:
        validate_upload(
            file,
            max_size=settings.MAX_CONFERENCE_FILE_SIZE,
            allowed_types=settings.ALLOWED_CONFERENCE_FILE_TYPES,
        )
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    try:
        filename = sanitize_filename(file.name)
    except ValueError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    @sync_to_async
    def save_file() -> tuple[int, ConferenceFile]:
        new_file_name: str | None = None
        try:
            with Mutex.lock_in_transaction(
                f"{conference.pk}:{conference_file_name}",
                namespace="conference_files",
            ):
                existing = (
                    ConferenceFile.objects.select_related("conference")
                    .filter(
                        conference=conference,
                        name=conference_file_name,
                    )
                    .first()
                )

                old_file_name = existing.file.name if existing else None
                created = existing is None

                conference_file_obj = existing or ConferenceFile(
                    conference=conference,
                    name=conference_file_name,
                )
                conference_file_obj.filename = filename
                conference_file_obj.file.save(file.name, file, save=False)
                new_file_name = conference_file_obj.file.name
                conference_file_obj.save()

                if old_file_name and old_file_name != new_file_name:
                    storage = conference_file_obj.file.storage
                    transaction.on_commit(partial(storage.delete, old_file_name))

            status_code = HTTPStatus.CREATED if created else HTTPStatus.OK
            return status_code, conference_file_obj
        except Exception:
            if new_file_name:
                conference_file_obj.file.storage.delete(new_file_name)
            raise

    status, conference_file = await save_file()

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_FILE_UPLOAD,
        resource=conference_file,
        scope=conference_name,
        payload={"file": {"name": file.name or "", "size": file.size or 0}},
    )

    return status, conference_file


@router.delete(
    "/conferences/{slug:conference_name}/files/{slug:conference_file_name}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Conference File",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def delete_conference_file(
    request: AuthedHttpRequest,
    conference_name: str,
    conference_file_name: str,
) -> tuple[int, None]:
    """Delete a shared conference file and its stored content."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    conference_file = await aget_object_or_404(
        conference.files.select_related("conference"),
        name=conference_file_name,
    )

    file_name = conference_file.file.name
    storage = conference_file.file.storage

    @sync_to_async
    def perform_delete() -> None:
        with transaction.atomic():
            conference_file.delete()
            transaction.on_commit(partial(storage.delete, file_name))

    await perform_delete()

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_FILE_DELETE,
        resource=conference_file,
        scope=conference_name,
    )

    return HTTPStatus.NO_CONTENT, None

from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.models import PaperFinal, PaperSubmission
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.utils.files import build_file_download_response

from .core import router


@lru_cache(maxsize=1)
def _get_extension_mime_map() -> dict[str, str]:
    """Build a reverse mapping from file extension to MIME type.

    Derives the mapping from the allowed upload type settings so that download
    content-type detection stays in sync with what the app accepts on upload.
    """
    ext_map: dict[str, str] = {}
    for types_map in (
        settings.ALLOWED_SUBMISSION_TYPES,
        settings.ALLOWED_FINAL_SOURCE_TYPES,
        settings.ALLOWED_FINAL_VIEWABLE_TYPES,
    ):
        for mime_type, extensions in types_map.items():
            for ext in extensions:
                ext_map.setdefault(ext.lower(), mime_type)
    return ext_map


def guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename extension using allowed upload types.

    Falls back to ``application/octet-stream`` for unknown extensions.

    >>> guess_mime_type("paper.pdf")
    'application/pdf'
    >>> guess_mime_type("paper.docx")
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    >>> guess_mime_type("archive.zip")
    'application/zip'
    >>> guess_mime_type("file.unknownext")
    'application/octet-stream'
    """
    ext = Path(filename).suffix.lower()
    return _get_extension_mime_map().get(ext, "application/octet-stream")


DOWNLOAD_FILE_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        }
    }
}


@router.get(
    "/conferences/-/paper-submissions/{ulid:uid}",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Submission",
    auth=is_authenticated,
)
async def download_submission(
    request: AuthedHttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper submission file."""
    submission = await aget_object_or_404(
        PaperSubmission.objects.select_related("paper"),
        uid=uid,
    )
    try:
        return build_file_download_response(
            submission.file,
            filename=submission.display_name,
            content_type=guess_mime_type(submission.file.name),  # type: ignore[arg-type]
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


@router.get(
    "/conferences/-/paper-finals/{ulid:uid}",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Final Source",
    auth=is_authenticated,
)
async def download_final(
    request: AuthedHttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper final source file."""
    final = await aget_object_or_404(
        PaperFinal.objects.select_related("paper"),
        uid=uid,
    )
    try:
        return build_file_download_response(
            final.source_file,
            filename=final.display_name,
            content_type=guess_mime_type(final.source_file.name),  # type: ignore[arg-type]
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


@router.get(
    "/conferences/-/paper-finals/{ulid:uid}/viewable",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Final Viewable",
    auth=is_authenticated,
)
async def download_final_viewable(
    request: AuthedHttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper final viewable file."""
    final = await aget_object_or_404(
        PaperFinal.objects.select_related("paper"),
        uid=uid,
    )
    if not final.viewable_file:
        raise Http404
    try:
        return build_file_download_response(
            final.viewable_file,
            filename=final.viewable_display_name,
            content_type=guess_mime_type(final.viewable_file.name),  # type: ignore[arg-type]
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


# Routes with {str:filename} must be registered after more specific routes (e.g.,
# /viewable) to prevent the filename parameter from matching literal path segments.


@router.get(
    "/conferences/-/paper-submissions/{ulid:uid}/{str:filename}",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Submission",
    auth=is_authenticated,
)
async def download_submission_ex(
    request: AuthedHttpRequest,
    uid: ULID,
    filename: str,  # noqa: ARG001
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper submission file with a decorative filename segment."""
    return await download_submission(request, uid)


@router.get(
    "/conferences/-/paper-finals/{ulid:uid}/{str:filename}",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Final Source",
    auth=is_authenticated,
)
async def download_final_ex(
    request: AuthedHttpRequest,
    uid: ULID,
    filename: str,  # noqa: ARG001
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper final source file with a decorative filename segment."""
    return await download_final(request, uid)


@router.get(
    "/conferences/-/paper-finals/{ulid:uid}/viewable/{str:filename}",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Final Viewable",
    auth=is_authenticated,
)
async def download_final_viewable_ex(
    request: AuthedHttpRequest,
    uid: ULID,
    filename: str,  # noqa: ARG001
) -> HttpResponse | StreamingHttpResponse:
    """Download a paper final viewable file with a decorative filename segment."""
    return await download_final_viewable(request, uid)

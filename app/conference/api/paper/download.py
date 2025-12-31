import mimetypes

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.models import PaperFinal, PaperSubmission
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.utils.files import build_file_download_response

from .core import router

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
    content_type = (
        mimetypes.guess_type(submission.file.name)[0] or "application/octet-stream"
    )
    try:
        return build_file_download_response(
            submission.file,
            filename=submission.display_name,
            content_type=content_type,
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
    content_type = (
        mimetypes.guess_type(final.source_file.name)[0] or "application/octet-stream"
    )
    try:
        return build_file_download_response(
            final.source_file,
            filename=final.display_name,
            content_type=content_type,
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
    content_type = (
        mimetypes.guess_type(final.viewable_file.name)[0] or "application/octet-stream"
    )
    try:
        return build_file_download_response(
            final.viewable_file,
            filename=final.viewable_display_name,
            content_type=content_type,
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

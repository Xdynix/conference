import mimetypes

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.models import PaperSubmission
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.utils.files import build_file_download_response

from .core import router

DOWNLOAD_SUBMISSION_OPENAPI_EXTRA = {
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
    openapi_extra=DOWNLOAD_SUBMISSION_OPENAPI_EXTRA,
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
    "/conferences/-/paper-submissions/{ulid:uid}/{str:filename}",
    openapi_extra=DOWNLOAD_SUBMISSION_OPENAPI_EXTRA,
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

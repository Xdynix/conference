from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from ninja import Router
from ulid import ULID

from app.conference.models import PaperProof
from app.utils.files import build_file_download_response

router = Router(tags=["Proof"], exclude_none=True)

DOWNLOAD_FILE_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    }
}


@router.get(
    "/conferences/-/paper-proofs/{ulid:uid}/file",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Proof File",
    auth=None,
)
async def download_proof_file(
    request: HttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Download the proof PDF for a paper."""
    proof = await aget_object_or_404(
        PaperProof.objects.select_related("paper"),
        uid=uid,
    )
    if not proof.file:
        raise Http404
    try:
        return build_file_download_response(
            proof.file,
            filename=f"{proof.paper.code}-proof.pdf",
            content_type="application/pdf",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise Http404 from exc

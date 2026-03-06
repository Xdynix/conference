from django.conf import settings
from django.http import Http404, HttpResponse
from ninja import Router

from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest

router = Router(tags=["Doc"], exclude_none=True)

DOCS: dict[str, str] = {
    "batch-import-guide": "docs/batch-import-api-guide.md",
    "email-sending-guide": "docs/email-sending-api-guide.md",
}


@router.get(
    "/conferences/{slug:conference_name}/docs/{str:doc_name}",
    openapi_extra={
        "responses": {
            200: {
                "content": {
                    "text/markdown": {
                        "schema": {"type": "string"},
                    },
                }
            }
        }
    },
    summary="Get Doc",
    auth=is_authenticated,
)
async def get_doc(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,  # noqa: ARG001
    doc_name: str,
) -> HttpResponse:
    """Serve a raw documentation file by name."""
    relative_path = DOCS.get(doc_name)
    if relative_path is None:
        raise Http404

    file_path = settings.BASE_DIR / relative_path
    content = file_path.read_text(encoding="utf-8")

    return HttpResponse(content, content_type="text/markdown; charset=utf-8")

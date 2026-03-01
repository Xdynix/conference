from django.conf import settings
from django.http import Http404, HttpResponse
from ninja import Router

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import ConferenceRole, TrackRole
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

router = Router(tags=["Doc"], exclude_none=True)

DOCS: dict[str, str] = {
    "batch-import-guide": "docs/batch-import-api-guide.md",
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
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
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

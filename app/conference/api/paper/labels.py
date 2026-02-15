from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja import Body

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Paper
from app.conference.services import PaperService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.utils.label_selector import LabelKey, LabelValue

from .core import PaperDetailResponse, prefetch_paper, router


@router.put(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/labels",
    response=PaperDetailResponse,
    summary="Update Paper Labels",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def update_paper_labels(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: Body[dict[LabelKey, LabelValue]],
) -> Paper:
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    await sync_to_async(PaperService.set_paper_labels)(paper, **payload)  # type: ignore[misc]

    await audit(
        request=request,
        action=AuditAction.PAPER_SET_LABELS,
        resource=paper,
        scope=conference.name,
        payload={str(k): str(v) for k, v in payload.items()},
    )

    return await prefetch_paper(conference, paper, user, request)

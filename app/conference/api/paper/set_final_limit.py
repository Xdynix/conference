from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja import Schema
from ninja.errors import HttpError
from pydantic import NonNegativeInt

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Paper
from app.conference.services import PaperService
from app.conference.services.paper import PaperWithdrawnError
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import PaperDetailResponse, prefetch_paper, router


class SetFinalLimitRequest(Schema):
    count: NonNegativeInt


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:set-final-limit",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Set Paper Final Limit",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def set_paper_final_limit(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: SetFinalLimitRequest,
) -> Paper:
    """Set the maximum number of final version uploads allowed for a paper."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    try:
        paper = await sync_to_async(PaperService.set_final_revision_limit)(
            paper=paper,
            count=payload.count,
        )
    except PaperWithdrawnError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_SET_FINAL_LIMIT,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_paper(conference, paper, user, request)

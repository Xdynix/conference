from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja.errors import HttpError

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Paper
from app.conference.services import ConferenceService, PaperService
from app.conference.services.paper import PaperWithdrawnError
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router


@router.post(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}:withdraw",
    response={
        HTTPStatus.OK: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Withdraw My Paper",
    auth=is_authenticated,
)
async def withdraw_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Withdraw a paper from consideration.

    Marks the paper as withdrawn. Withdrawal can happen from any state and is final.
    Withdrawn papers remain visible but cannot be edited or resubmitted.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active().filter(owner=user),
        code=paper_code,
    )

    try:
        paper = await sync_to_async(PaperService.withdraw_paper)(paper)
    except PaperWithdrawnError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_WITHDRAW,
        resource=paper,
        scope=conference.name,
    )

    return await prefetch_paper(conference, paper, user, request)


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:withdraw",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Withdraw Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def withdraw_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Withdraw a paper as conference chair.

    Marks the paper as withdrawn. Typically used when an author requests withdrawal
    offline and the chair records it in the system. Withdrawal is final.
    """
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
        paper = await sync_to_async(PaperService.withdraw_paper)(paper)
    except PaperWithdrawnError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_WITHDRAW,
        resource=paper,
        scope=conference.name,
    )

    return await prefetch_paper(conference, paper, user, request)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja.errors import HttpError

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import ConferenceService, PaperService
from app.conference.services.paper import PaperStateError, PaperSubmissionError
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router


@router.post(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}:submit",
    response={
        HTTPStatus.OK: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Submit My Paper",
    auth=is_authenticated,
)
async def submit_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> tuple[int, Paper | ErrorResponse]:
    """Submit a paper for review.

    Validates that all required fields are present (title, abstract, contribution,
    keywords, submission file, authors with required fields, and exactly one
    corresponding author) and transitions the paper from Draft to Submitted state.
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
        paper = await sync_to_async(PaperService.submit_paper)(paper, strict=True)
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except PaperSubmissionError as exc:
        return HTTPStatus.BAD_REQUEST, ErrorResponse(
            message=str(exc),
            details=exc.errors,
        )

    await audit(
        request=request,
        action=AuditAction.PAPER_SUBMIT,
        resource=paper,
        scope=conference.name,
    )

    return HTTPStatus.OK, await prefetch_paper(conference, paper, user, request)


@router.post(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}:unsubmit",
    response={
        HTTPStatus.OK: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Unsubmit My Paper",
    auth=is_authenticated,
)
async def unsubmit_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Unsubmit a paper to allow further editing.

    Transitions the paper from Submitted back to Draft state. Use this when you need to
    make changes after submission but before review starts.
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
        paper = await sync_to_async(PaperService.unsubmit_paper)(paper)
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_UNSUBMIT,
        resource=paper,
        scope=conference.name,
    )

    return await prefetch_paper(conference, paper, user, request)


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:submit",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Submit Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def submit_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> tuple[int, Paper | ErrorResponse]:
    """Submit a paper for review as an admin.

    Performs minimal validation (only title is required) and transitions the paper
    from Draft to Submitted state. Use this for invited papers or placeholder records
    that need to enter review directly.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        await PaperService.visible_papers(conference, user),
        code=paper_code,
    )

    try:
        paper = await sync_to_async(PaperService.submit_paper)(paper, strict=False)
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except PaperSubmissionError as exc:
        return HTTPStatus.BAD_REQUEST, ErrorResponse(
            message=str(exc),
            details=exc.errors,
        )

    await audit(
        request=request,
        action=AuditAction.PAPER_SUBMIT,
        resource=paper,
        scope=conference.name,
    )

    return HTTPStatus.OK, await prefetch_paper(conference, paper, user, request)

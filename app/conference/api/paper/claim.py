from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from django.shortcuts import aget_object_or_404
from ninja import Status
from ninja.errors import HttpError

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import ClaimService, PaperService
from app.conference.services.claim import ClaimConflictError
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import PaperDetailResponse, prefetch_paper, router


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:set-claim",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.NOT_FOUND: ErrorResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Set Paper Claim",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def set_paper_claim(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Create a claim on the paper for deferred ownership transfer.

    Derives the claim email from the paper's corresponding author. If a user with that
    email already exists, transfers ownership immediately. Otherwise, creates a claim
    for automatic transfer when the user registers.
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
        await sync_to_async(ClaimService.set_claim)(paper=paper)
    except ValueError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except ClaimConflictError as exc:
        raise HttpError(HTTPStatus.CONFLICT, str(exc)) from exc
    except Paper.DoesNotExist as exc:
        raise Http404 from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_SET_CLAIM,
        resource=paper,
        scope=conference.name,
    )

    return await prefetch_paper(conference, paper, user, request)


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:remove-claim",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Remove Paper Claim",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def remove_paper_claim(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Status[None]:
    """Remove the claim on a paper, cancelling any pending auto-transfer."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        await PaperService.visible_papers(conference, user),
        code=paper_code,
    )

    await sync_to_async(ClaimService.remove_claim)(paper=paper)

    await audit(
        request=request,
        action=AuditAction.PAPER_REMOVE_CLAIM,
        resource=paper,
        scope=conference.name,
    )

    return Status(HTTPStatus.NO_CONTENT, None)

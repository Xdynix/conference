from http import HTTPStatus
from typing import Annotated, Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja import Schema
from ninja.errors import HttpError
from pydantic import AwareDatetime, BeforeValidator, StringConstraints

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Paper,
    PaperDecision,
    PaperDecisionState,
    PaperState,
)
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError
from app.conference.types import ConferenceUser
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse
from app.utils.sanitization import sanitize_formatted_text

from .core import PaperDetailResponse, prefetch_paper, router

DecisionNote = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]


class PaperDecisionResponse(Schema):
    create_time: AwareDatetime
    decider: ConferenceUser
    state: Literal[
        PaperDecisionState.REJECTED,
        PaperDecisionState.ACCEPTED,
        PaperDecisionState.ACCEPTED_REVISION_NEEDED,
    ]
    note: DecisionNote


@router.get(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/decisions",
    response=list[PaperDecisionResponse],
    summary="List Paper Decisions",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def list_paper_decisions(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    paper_code: str,
) -> list[PaperDecision]:
    """Returns decision history for a paper."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    decisions = paper.decisions.select_related("decider__profile")

    return [decision async for decision in decisions]


class DecidePaperRequest(Schema):
    state: Literal[
        PaperState.REJECTED,
        PaperState.ACCEPTED,
        PaperState.ACCEPTED_REVISION_NEEDED,
    ]
    note: DecisionNote = ""


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:decide",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Decide Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def decide_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: DecidePaperRequest,
) -> Paper:
    """Make an accept or reject decision on a paper.

    Creates an audit record of the decision. Papers in any state except Draft can be
    decided, allowing for direct acceptance of invited papers or changing previous
    decisions. Withdrawn papers cannot be decided.
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
        paper = await sync_to_async(PaperService.decide_paper)(
            paper=paper,
            decider=user,
            state=PaperState(payload.state),
            note=payload.note,
        )
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_DECIDE,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_paper(conference, paper, user, request)

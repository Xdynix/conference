from typing import Annotated

from django.shortcuts import aget_object_or_404
from ninja import Schema
from pydantic import AwareDatetime, BeforeValidator, StringConstraints

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, PaperDecision
from app.conference.types import ConferenceUser
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.utils.sanitization import sanitize_formatted_text

from .core import router

DecisionNote = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]


class PaperDecisionResponse(Schema):
    create_time: AwareDatetime
    decider: ConferenceUser
    state: PaperDecision.State
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

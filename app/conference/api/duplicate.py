from typing import Annotated, Literal

from django.db.models import Q
from django.http import Http404
from django.shortcuts import aget_object_or_404
from ninja import Field, Router, Schema
from pydantic import AwareDatetime, BeforeValidator, StringConstraints
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    DuplicateMatchType,
    Paper,
    PaperState,
)
from app.conference.models.duplicate import (
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateReport,
    DuplicateReportState,
)
from app.conference.services.access import ConferenceAccessService
from app.conference.services.conference import ConferenceService
from app.conference.types import (
    ConferenceName,
    ConferenceUser,
    PaperCode,
    PaperTitle,
    PaperTrack,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.utils.sanitization import sanitize_formatted_text

router = Router(tags=["Duplicate Detection"], exclude_none=True)

MATCH_TYPE_ORDER: dict[str, int] = {
    DuplicateMatchType.FILE_HASH: 0,
    DuplicateMatchType.TITLE_SIMILARITY: 1,
}

DuplicateAcknowledgmentNote = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
    Field(""),
]


class DuplicatePaperSchema(Schema):
    visibility: Literal["visible", "conference_only", "redacted"]
    uid: ULID
    conference: ConferenceName | None
    track: PaperTrack | None
    code: PaperCode | None
    create_time: AwareDatetime | None
    state: PaperState | None
    withdraw_time: AwareDatetime | None
    title: PaperTitle | None


class DuplicateAcknowledgmentSchema(Schema):
    create_time: AwareDatetime
    update_time: AwareDatetime
    user: ConferenceUser | None
    note: DuplicateAcknowledgmentNote


class DuplicateMatchSchema(Schema):
    pair: tuple[DuplicatePaperSchema, DuplicatePaperSchema]
    match_type: DuplicateMatchType
    score: float = Field(ge=0.0, le=1.0)
    acknowledgment: DuplicateAcknowledgmentSchema | None


class DuplicateReportSchema(Schema):
    create_time: AwareDatetime
    matches: list[DuplicateMatchSchema]


@router.get(
    "/conferences/{slug:conference_name}/duplicate-report",
    response=DuplicateReportSchema,
    summary="Get Duplicate Report",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def get_duplicate_report(
    request: AuthedHttpRequest,
    conference_name: str,
) -> DuplicateReportSchema:
    """Returns the latest duplicate detection report for the conference.

    Only matches involving at least one paper in this conference are included. Each
    paper in a pair has a visibility level ("visible", "conference_only", or "redacted")
    depending on the requesting admin's access to that paper's conference.

    Matches are sorted with unacknowledged pairs first, then by descending score.
    Returns 404 if no successful report exists.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    user = await request.auser()

    report = await (
        DuplicateReport.objects.filter(state=DuplicateReportState.SUCCESS)
        .order_by("-create_time")
        .afirst()
    )
    if report is None:
        raise Http404

    matches = [
        m
        async for m in DuplicateMatch.objects.filter(report=report)
        .filter(
            Q(paper_a__conference=conference) | Q(paper_b__conference=conference),
        )
        .select_related(
            "paper_a__conference",
            "paper_a__track",
            "paper_b__conference",
            "paper_b__track",
        )
    ]

    distinct_conferences: dict[int, Conference] = {}
    for match in matches:
        for paper in (match.paper_a, match.paper_b):
            cid = paper.conference_id
            distinct_conferences[cid] = paper.conference

    visible_conferences = await ConferenceService.visible_conferences(user)
    visible_conference_ids = {
        pk
        async for pk in visible_conferences.filter(
            pk__in=distinct_conferences
        ).values_list("pk", flat=True)
    }

    admin_conference_ids: set[int] = set()
    for conf in distinct_conferences.values():
        ctx = await ConferenceAccessService.context(conference=conf, user=user)
        if ctx.has_full_conference_scope:
            admin_conference_ids.add(conf.pk)

    ack_map: dict[tuple[int, int], DuplicateAcknowledgment] = {
        (ack.paper_a_id, ack.paper_b_id): ack
        async for ack in conference.duplicate_acknowledgments.select_related(
            "user__profile"
        )
    }

    matches.sort(
        key=lambda m: (
            # Unacknowledged first.
            (m.paper_a_id, m.paper_b_id) in ack_map,
            # Descending score.
            -m.score,
            # File hash, then title similarity.
            MATCH_TYPE_ORDER.get(m.match_type, 99),
        ),
    )

    return DuplicateReportSchema(
        create_time=report.create_time,
        matches=[
            DuplicateMatchSchema(
                pair=(
                    _paper_view(
                        m.paper_a,
                        admin_conference_ids,
                        visible_conference_ids,
                    ),
                    _paper_view(
                        m.paper_b,
                        admin_conference_ids,
                        visible_conference_ids,
                    ),
                ),
                match_type=m.match_type,  # type: ignore[arg-type]
                score=m.score,
                acknowledgment=(
                    DuplicateAcknowledgmentSchema.model_validate(ack)
                    if (ack := ack_map.get((m.paper_a_id, m.paper_b_id)))
                    else None
                ),
            )
            for m in matches
        ],
    )


def _paper_view(
    paper: Paper,
    admin_conference_ids: set[int],
    visible_conference_ids: set[int],
) -> DuplicatePaperSchema:
    cid = paper.conference_id
    if cid in admin_conference_ids:
        return DuplicatePaperSchema(
            visibility="visible",
            uid=paper.uid,
            conference=paper.conference.name,
            track=paper.track,  # type: ignore[arg-type]
            code=paper.code,
            create_time=paper.create_time,
            state=paper.state,  # type: ignore[arg-type]
            withdraw_time=paper.withdraw_time,
            title=paper.title,
        )
    if cid in visible_conference_ids:
        return DuplicatePaperSchema(
            visibility="conference_only",
            uid=paper.uid,
            conference=paper.conference.name,
            track=None,
            code=None,
            create_time=None,
            state=None,
            withdraw_time=None,
            title=None,
        )
    return DuplicatePaperSchema(
        visibility="redacted",
        uid=paper.uid,
        conference=None,
        track=None,
        code=None,
        create_time=None,
        state=None,
        withdraw_time=None,
        title=None,
    )

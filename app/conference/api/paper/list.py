from typing import Annotated

from django.db.models import Q, QuerySet
from django.shortcuts import aget_object_or_404
from ninja import Field, FilterSchema, Query
from ninja.pagination import paginate
from pydantic import AfterValidator, StringConstraints

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Paper,
    PaperLabel,
    TrackRole,
)
from app.conference.services import ConferenceService, PaperService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import CursorPagination
from app.utils.label_selector import LabelSelector

from .core import PaperResponse, UserPaperResponse, router, with_paper_prefetch

# TODO: Filtering and searching.


@router.get(
    "/conferences/{slug:conference_name}/my-papers",
    response=list[UserPaperResponse],
    summary="List My Papers",
    auth=is_authenticated,
)
@paginate(CursorPagination, cursor_field="uid")
async def list_my_papers(
    request: AuthedHttpRequest,
    conference_name: str,
) -> QuerySet[Paper]:
    """Returns papers owned by the current user.

    Papers with a decision (accepted, rejected) show as "Under Review" until the
    decision is announced.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    papers = conference.papers.active().filter(owner=user)

    return await with_paper_prefetch(papers, conference, user)


LabelSelectorStr = Annotated[
    str,
    StringConstraints(max_length=4096, strip_whitespace=True),
    AfterValidator(LabelSelector.from_str),
]


class ListPapersFilters(FilterSchema):
    label_selector: LabelSelectorStr | None = Field(
        None,
        description=(
            "Filter papers by labels using Kubernetes-style selector syntax. "
            "Supports equality (=, ==, !=), set membership (in, notin), "
            "and existence checks (key, !key). Multiple requirements are ANDed."
        ),
        examples=[
            "env=prod",
            "tier in (frontend,backend)",
            "env=prod, !experimental",
        ],
    )

    @classmethod
    def filter_label_selector(cls, value: LabelSelector | None) -> Q:
        if value is None:
            return Q()
        return PaperLabel.selector_q(value)


@router.get(
    "/conferences/{slug:conference_name}/papers",
    response=list[PaperResponse],
    summary="List Papers",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
@paginate(CursorPagination, cursor_field="uid")
async def list_papers(
    request: AuthedHttpRequest,
    conference_name: str,
    filters: Query[ListPapersFilters],
) -> QuerySet[Paper]:
    """Returns papers visible to the current admin user.

    Conference admins see all papers. Track admins see only papers in their tracks.
    The `state` field reflects the actual decision immediately. `visible_state`
    provides the announcement-aware value when clients need both.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    papers = await PaperService.visible_papers(conference, user)
    papers = filters.filter(papers)

    return await with_paper_prefetch(papers, conference, user)

from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja.pagination import paginate

from app.conference.models import Paper
from app.conference.services import ConferenceService
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import CursorPagination

from .core import UserPaperResponse, router, with_paper_prefetch

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
    conferences = await ConferenceService.visible_conferences(user)
    conference = await aget_object_or_404(conferences, name=conference_name)

    papers = conference.papers.active().filter(owner=user)

    return with_paper_prefetch(papers)

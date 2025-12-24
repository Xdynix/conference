from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja.pagination import paginate

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import ConferenceService, PaperService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import CursorPagination

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

    return await with_paper_prefetch(papers, conference, user)

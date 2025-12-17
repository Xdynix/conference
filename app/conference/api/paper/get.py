from django.shortcuts import aget_object_or_404

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import ConferenceService, PaperService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router


@router.get(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}",
    response=UserPaperDetailResponse,
    summary="Get My Paper",
    auth=is_authenticated,
)
async def get_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Returns detailed information about a paper owned by the current user.

    Includes all metadata, authors, and keywords. The decision state remains masked
    as "Under Review" until the decision is announced.
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

    return await prefetch_paper(paper)


@router.get(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}",
    response=PaperDetailResponse,
    summary="Get Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def get_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> Paper:
    """Returns detailed information about a paper.

    Conference admins can view all papers. Track admins can only view papers in their
    tracks. The actual decision state is always visible regardless of announcement
    status.
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

    return await prefetch_paper(paper)

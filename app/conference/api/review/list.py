from django.shortcuts import aget_object_or_404

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Review, TrackRole
from app.conference.services import ConferenceService, PaperService, ReviewService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import ReviewResponse, UserReviewResponse, router, with_review_prefetch

# TODO: Filtering


@router.get(
    "/conferences/{slug:conference_name}/my-reviews",
    response=list[UserReviewResponse],
    summary="List My Reviews",
    auth=is_authenticated,
)
async def list_my_reviews(
    request: AuthedHttpRequest,
    conference_name: str,
) -> list[Review]:
    """Returns reviews assigned to the current user."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    reviews = (
        Review.objects.active()
        .filter(paper__conference=conference, reviewer=user)
        .exclude(state=Review.State.CANCELLED)
        .order_by("uid")
    )

    return [review async for review in with_review_prefetch(reviews)]


@router.get(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/reviews",
    response=list[ReviewResponse],
    summary="List Reviews",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def list_reviews(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> list[Review]:
    """Returns reviews for a paper visible to the current admin user.

    Conference admins see all reviews. Track admins see only track-level reviews for
    papers in their tracks.
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

    reviews = await ReviewService.visible_reviews(conference=conference, user=user)
    reviews = reviews.filter(paper=paper).order_by("uid")

    return [review async for review in with_review_prefetch(reviews)]

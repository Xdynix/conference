from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Review,
    ReviewState,
    TrackRole,
)
from app.conference.services import ConferenceService, ReviewService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import (
    ReviewDetailResponse,
    UserReviewDetailResponse,
    prefetch_review,
    router,
)


@router.get(
    "/conferences/{slug:conference_name}/my-reviews/{ulid:review_uid}",
    response=UserReviewDetailResponse,
    summary="Get My Review",
    auth=is_authenticated,
)
async def get_my_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Returns a review assigned to the current user with full details."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    reviews = (
        Review.objects.active()
        .filter(paper__conference=conference, reviewer=user)
        .exclude(state=ReviewState.CANCELLED)
    )

    review = await aget_object_or_404(reviews, uid=review_uid)
    return await prefetch_review(review, request)


@router.get(
    "/conferences/{slug:conference_name}/reviews/{ulid:review_uid}",
    response=ReviewDetailResponse,
    summary="Get Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def get_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Returns a review visible to the current admin user.

    Conference admins see all reviews. Track admins see only track-level reviews for
    papers in their tracks.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    reviews = await ReviewService.visible_reviews(conference=conference, user=user)

    review = await aget_object_or_404(reviews, uid=review_uid)
    return await prefetch_review(review, request)

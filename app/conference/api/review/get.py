from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.models import Review
from app.conference.services import ConferenceService
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest

from .core import UserReviewDetailResponse, prefetch_review, router


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
        .exclude(state=Review.State.CANCELLED)
    )

    review = await aget_object_or_404(reviews, uid=review_uid)
    return await prefetch_review(review)

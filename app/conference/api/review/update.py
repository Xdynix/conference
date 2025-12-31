from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import PatchDict, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Review, ReviewState
from app.conference.services import ConferenceService, ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.conference.types import ReviewComment, ReviewScore
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import (
    ReviewDetailResponse,
    UserReviewDetailResponse,
    prefetch_review,
    router,
)


class ReviewSchema(Schema):
    originality: ReviewScore
    significance: ReviewScore
    technical: ReviewScore
    reference: ReviewScore
    presentation: ReviewScore
    match_topic: ReviewScore
    recommendation: ReviewScore
    contribution: ReviewComment
    decision_reason: ReviewComment
    comments: ReviewComment
    confidential_remarks: ReviewComment


@router.patch(
    "/conferences/{slug:conference_name}/my-reviews/{ulid:review_uid}",
    response={
        HTTPStatus.OK: UserReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Update My Review",
    auth=is_authenticated,
)
async def update_my_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
    payload: PatchDict[ReviewSchema],
) -> Review:
    """Save draft review scores and text fields.

    Only reviews in Accepted state can be updated. All fields are optional; omitted
    fields retain their existing values.
    """
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

    try:
        updated = await sync_to_async(ReviewService.update_review)(
            review,
            mode="reviewer",
            **payload,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review draft saved.",
        review_uid=str(review.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_review(updated, request)


@router.patch(
    "/conferences/{slug:conference_name}/reviews/{ulid:review_uid}",
    response={
        HTTPStatus.OK: ReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Update Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(*ConferenceRole.admins())
    ),
)
async def update_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
    payload: PatchDict[ReviewSchema],
) -> Review:
    """Update review scores and text fields as an admin.

    Only reviews in Accepted or Submitted state can be updated. All fields are optional;
    omitted fields retain their existing values.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    reviews = await ReviewService.visible_reviews(conference=conference, user=user)

    review = await aget_object_or_404(reviews, uid=review_uid)

    try:
        updated = await sync_to_async(ReviewService.update_review)(
            review,
            mode="admin",
            **payload,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review updated by admin.",
        review_uid=str(review.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_review(updated, request)

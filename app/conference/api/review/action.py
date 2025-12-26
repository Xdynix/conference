from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError
from ulid import ULID

from app.conference.models import Review
from app.conference.services import ConferenceService, ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import UserReviewDetailResponse, prefetch_review, router


@router.post(
    "/conferences/{slug:conference_name}/my-reviews/{ulid:review_uid}:accept",
    response={
        HTTPStatus.OK: UserReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Accept Review Assignment",
    auth=is_authenticated,
)
async def accept_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Accept a review assignment."""
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

    try:
        review = await sync_to_async(ReviewService.respond_to_assignment)(
            review=review,
            response=Review.State.ACCEPTED,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review assignment accepted.",
        conference_name=conference.name,
        review_uid=review.uid,
        reviewer_uid=user.uid,
    )

    return await prefetch_review(review)


@router.post(
    "/conferences/{slug:conference_name}/my-reviews/{ulid:review_uid}:decline",
    response={
        HTTPStatus.OK: UserReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Decline Review Assignment",
    auth=is_authenticated,
)
async def decline_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Decline a review assignment."""
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

    try:
        review = await sync_to_async(ReviewService.respond_to_assignment)(
            review=review,
            response=Review.State.DECLINED,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review assignment declined.",
        conference_name=conference.name,
        review_uid=review.uid,
        reviewer_uid=user.uid,
    )

    return await prefetch_review(review)

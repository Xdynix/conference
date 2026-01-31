from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import (
    has_any_conference_or_track_roles,
    has_any_conference_roles,
)
from app.conference.models import (
    Conference,
    ConferenceRole,
    Review,
    ReviewState,
    TrackRole,
)
from app.conference.services import (
    ConferenceAccessService,
    ConferenceService,
    ReviewService,
)
from app.conference.services.review import (
    InvalidReviewStateError,
    ReviewSubmissionError,
)
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


@router.post(
    "/conferences/{slug:conference_name}/my-reviews/{ulid:review_uid}:submit",
    response={
        HTTPStatus.OK: UserReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Submit My Review",
    auth=is_authenticated,
)
async def submit_my_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> tuple[int, Review | ErrorResponse]:
    """Submit a review for a paper.

    Validates that all required fields are present (scores, contribution, decision
    reason) and transitions the review from Accepted to Submitted state.
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
        review = await sync_to_async(ReviewService.submit_review)(review, strict=True)
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except ReviewSubmissionError as exc:
        return HTTPStatus.BAD_REQUEST, ErrorResponse(
            message=str(exc),
            details=exc.errors,
        )

    logger.info(
        "Review submitted by reviewer.",
        review_uid=str(review.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return HTTPStatus.OK, await prefetch_review(review, request)


@router.post(
    "/conferences/{slug:conference_name}/reviews/{ulid:review_uid}:submit",
    response={
        HTTPStatus.OK: ReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Submit Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def submit_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Submit a review on behalf of a reviewer. Skips field validation."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    reviews = await ReviewService.visible_reviews(conference=conference, user=user)

    review = await aget_object_or_404(reviews, uid=review_uid)

    try:
        review = await sync_to_async(ReviewService.submit_review)(review, strict=False)
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review submitted by admin.",
        review_uid=str(review.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return await prefetch_review(review, request)


@router.post(
    "/conferences/{slug:conference_name}/reviews/{ulid:review_uid}:unsubmit",
    response={
        HTTPStatus.OK: ReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Unsubmit Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def unsubmit_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Unsubmit a review, returning it to Accepted state for revision.

    Allows admins to send a submitted review back to the reviewer for corrections.
    Not applicable to offline reviews. Track admins cannot unsubmit reviews for papers
    after decision announcement.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    reviews = await ReviewService.visible_reviews(conference=conference, user=user)

    review = await aget_object_or_404(reviews, uid=review_uid)

    ctx = await ConferenceAccessService.context(
        conference=conference,
        user=user,
        global_roles=(GlobalRole.ADMIN,),
    )
    mode: Literal["conference", "track"] = (
        "conference" if ctx.has_full_conference_scope else "track"
    )

    try:
        review = await sync_to_async(ReviewService.unsubmit_review)(review, mode=mode)
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Review unsubmitted by admin.",
        review_uid=str(review.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return await prefetch_review(review, request)

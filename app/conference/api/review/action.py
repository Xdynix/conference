from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
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
from app.conference.services.review import InvalidReviewStateError
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
        .exclude(state=ReviewState.CANCELLED)
    )

    review = await aget_object_or_404(reviews, uid=review_uid)

    try:
        review = await sync_to_async(ReviewService.respond_to_assignment)(
            review,
            response=ReviewState.ACCEPTED,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.REVIEW_ACCEPT,
        resource=review,
        scope=conference.name,
    )

    return await prefetch_review(review, request)


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
        .exclude(state=ReviewState.CANCELLED)
    )

    review = await aget_object_or_404(reviews, uid=review_uid)

    try:
        review = await sync_to_async(ReviewService.respond_to_assignment)(
            review,
            response=ReviewState.DECLINED,
        )
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.REVIEW_DECLINE,
        resource=review,
        scope=conference.name,
    )

    return await prefetch_review(review, request)


@router.post(
    "/conferences/{slug:conference_name}/reviews/{ulid:review_uid}:cancel",
    response={
        HTTPStatus.OK: ReviewDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Cancel Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def cancel_review(
    request: AuthedHttpRequest,
    conference_name: str,
    review_uid: ULID,
) -> Review:
    """Cancel a review assignment.

    Transitions a review to Cancelled state. The review remains visible in admin queries
    and counts, but is hidden from the reviewer's own views. Can be used for reviews in
    Pending, Accepted, or Submitted states. Track admins cannot cancel reviews for
    papers after decision announcement.
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
        review = await sync_to_async(ReviewService.cancel_review)(review, mode=mode)
    except InvalidReviewStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.REVIEW_CANCEL,
        resource=review,
        scope=conference.name,
    )

    return await prefetch_review(review, request)

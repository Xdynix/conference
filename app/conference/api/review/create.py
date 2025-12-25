from http import HTTPStatus

from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Review, TrackRole
from app.conference.services import PaperService, ReviewService
from app.conference.services.review import (
    AssignerNotAuthorizedError,
    ReviewerNotEligibleError,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import ReviewDetailResponse, prefetch_review, router


class AssignReviewRequest(Schema):
    reviewer: ULID


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/reviews:assign",
    response={
        HTTPStatus.CREATED: ReviewDetailResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Assign Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def assign_review(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: AssignReviewRequest,
) -> tuple[int, Review]:
    """Assign a reviewer to a paper.

    Creates a review assignment in PENDING state. The reviewer must accept the
    assignment before they can access the paper and submit their review.
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

    try:
        reviewer = await User.objects.active().aget(uid=payload.reviewer)
    except User.DoesNotExist as exc:
        raise make_validation_error(
            path="reviewer",
            message=_("User not found."),
        ) from exc

    try:
        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=user,
        )
    except AssignerNotAuthorizedError as exc:
        raise HttpError(HTTPStatus.FORBIDDEN, str(exc)) from exc
    except ReviewerNotEligibleError as exc:
        raise make_validation_error(path="reviewer", message=str(exc)) from exc
    except IntegrityError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("Reviewer already has an active review for this paper."),
        ) from exc

    logger.info(
        "Reviewer assigned.",
        conference_name=conference.name,
        paper_code=paper.code,
        reviewer_uid=reviewer.uid,
        assigner_uid=user.uid,
    )

    return HTTPStatus.CREATED, await prefetch_review(review)

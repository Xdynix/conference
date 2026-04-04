from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from ninja import Schema, Status
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Review,
    ReviewAssignmentLevel,
    ReviewState,
    TrackRole,
)
from app.conference.services import ConferenceAccessService, PaperService, ReviewService
from app.conference.services.paper import PaperStateError
from app.conference.services.review import ReviewerNotEligibleError
from app.conference.types import ReviewComment, ReviewOfflineReviewerName, ReviewScore
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
        HTTPStatus.BAD_REQUEST: ErrorResponse,
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
) -> Status:
    """Assign a reviewer to a paper.

    Creates a review assignment in PENDING state. The reviewer must accept the
    assignment before they can access the paper and submit their review. Transitions
    the paper from Submitted to Under Review on first assignment.
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

    ctx = await ConferenceAccessService.context(
        conference=conference,
        user=user,
        global_roles=(GlobalRole.ADMIN,),
    )
    mode: Literal["conference", "track"]
    if ctx.has_full_conference_scope:
        mode = "conference"
    elif paper.track_id in ctx.administered_track_ids:  # pragma: no branch
        mode = "track"
    else:
        raise AssertionError(
            "Unreachable: auth passed but no access scope."
        )  # pragma: no cover

    try:
        review = await sync_to_async(ReviewService.assign_reviewer)(
            paper=paper,
            reviewer=reviewer,
            assigner=user,
            mode=mode,
        )
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except ReviewerNotEligibleError as exc:
        raise make_validation_error(path="reviewer", message=str(exc)) from exc
    except IntegrityError as exc:
        is_conflict = await Review.objects.filter(
            paper=paper,
            reviewer=reviewer,
            state__in=ReviewState.active(),
        ).aexists()
        if not is_conflict:  # pragma: no cover
            raise
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("Reviewer already has an active review for this paper."),
        ) from exc

    await audit(
        request=request,
        action=AuditAction.REVIEW_ASSIGN,
        resource=review,
        scope=conference.name,
        payload=payload,
    )

    return Status(HTTPStatus.CREATED, await prefetch_review(review, request))


class ImportReviewRequest(Schema):
    offline_reviewer_name: ReviewOfflineReviewerName = ""
    originality: ReviewScore | None = None
    significance: ReviewScore | None = None
    technical: ReviewScore | None = None
    reference: ReviewScore | None = None
    presentation: ReviewScore | None = None
    match_topic: ReviewScore | None = None
    recommendation: ReviewScore | None = None
    contribution: ReviewComment = ""
    decision_reason: ReviewComment = ""
    comments: ReviewComment = ""
    confidential_remarks: ReviewComment = ""


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/reviews:import",
    response={
        HTTPStatus.OK: ReviewDetailResponse,
        HTTPStatus.CREATED: ReviewDetailResponse,
    },
    summary="Import Review",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(*ConferenceRole.admins())
    ),
)
async def import_review(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: ImportReviewRequest,
) -> Status:
    """Import a review from an external source.

    Creates or updates a review with no assigned reviewer in SUBMITTED state. If a
    review with the same `offline_reviewer_name` already exists for this paper, it will
    be updated. Used for importing reviews collected outside the system.
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

    defaults = {
        "state": ReviewState.SUBMITTED,
        "assigner": user,
        "assignment_level": ReviewAssignmentLevel.CONFERENCE,
        "submit_time": timezone.now(),
        "originality": payload.originality,
        "significance": payload.significance,
        "technical": payload.technical,
        "reference": payload.reference,
        "presentation": payload.presentation,
        "match_topic": payload.match_topic,
        "recommendation": payload.recommendation,
        "contribution": payload.contribution,
        "decision_reason": payload.decision_reason,
        "comments": payload.comments,
        "confidential_remarks": payload.confidential_remarks,
    }

    if payload.offline_reviewer_name:
        review, created = await Review.objects.aupdate_or_create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name=payload.offline_reviewer_name,
            defaults=defaults,
        )
        review.paper = paper
    else:
        review = await Review.objects.acreate(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="",
            **defaults,
        )
        created = True

    await audit(
        request=request,
        action=AuditAction.REVIEW_IMPORT,
        resource=review,
        scope=conference.name,
        payload=payload,
        detail={"created": created},
    )

    status = HTTPStatus.CREATED if created else HTTPStatus.OK
    return Status(status, await prefetch_review(review, request))

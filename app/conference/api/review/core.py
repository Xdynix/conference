from django.db.models import QuerySet
from ninja import Router

from app.conference.models import Paper, PaperSubmission, Review
from app.conference.models.review import ReviewAssignmentLevel
from app.conference.types import (
    ConferenceUser,
    ReviewDetailMixin,
    ReviewOfflineReviewerName,
    ReviewPaper,
)
from app.conference.types import PaperSubmission as PaperSubmissionSchema
from app.conference.types import Review as ReviewSchema

router = Router(tags=["Review"], exclude_none=True)


class ReviewPaperResponse(ReviewPaper):
    @staticmethod
    def resolve_conference(paper: Paper) -> str:
        return paper.conference.name

    @staticmethod
    def resolve_submission(paper: Paper) -> PaperSubmissionSchema | None:
        latest: PaperSubmission | None = next(iter(paper.latest_submission), None)  # type: ignore[attr-defined]
        if latest is None:
            return None
        return PaperSubmissionSchema(
            uid=latest.uid,
            display_name=latest.display_name,
        )


class BaseReviewResponse(ReviewSchema):
    paper: ReviewPaperResponse


class UserReviewResponse(BaseReviewResponse):
    pass


class UserReviewDetailResponse(ReviewDetailMixin, UserReviewResponse):
    pass


class ReviewResponse(BaseReviewResponse):
    reviewer: ConferenceUser | None
    offline_reviewer_name: ReviewOfflineReviewerName
    assigner: ConferenceUser | None
    assignment_level: ReviewAssignmentLevel


class ReviewDetailResponse(ReviewDetailMixin, ReviewResponse):
    pass


def with_review_prefetch(queryset: QuerySet[Review]) -> QuerySet[Review]:
    """Prefetch related data for review queries."""
    return queryset.select_related(
        "paper__conference",
        "paper__track",
        "reviewer__profile",
        "assigner__profile",
    ).prefetch_related(
        PaperSubmission.prefetch_latest(lookup="paper__submissions"),
    )


async def prefetch_review(review: Review) -> Review:
    """Refetch a review with all related data prefetched for serialization."""
    qs = with_review_prefetch(Review.objects.all())
    return await qs.aget(pk=review.pk)

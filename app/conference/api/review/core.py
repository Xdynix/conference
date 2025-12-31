from urllib.parse import urljoin

from django.db.models import CharField, Prefetch, QuerySet, Value
from django.http import HttpRequest
from django.urls import reverse
from ninja import Router
from pydantic import HttpUrl

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
        base_url: str = paper.api_base_url  # type: ignore[attr-defined]
        path = reverse(
            "api-1.0.0:download-submission-ex",
            args=[latest.uid, latest.display_name],
        )
        return PaperSubmissionSchema(
            uid=latest.uid,
            display_name=latest.display_name,
            download_url=HttpUrl(urljoin(base_url, path)),
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


def with_review_prefetch(
    queryset: QuerySet[Review],
    request: HttpRequest,
) -> QuerySet[Review]:
    """Prefetch related data for review queries."""
    return queryset.select_related(
        "reviewer__profile",
        "assigner__profile",
    ).prefetch_related(
        Prefetch(
            "paper",
            queryset=Paper.objects.select_related(
                "conference",
                "track__conference",
            ).annotate(
                api_base_url=Value(
                    request.build_absolute_uri("/"),
                    output_field=CharField(),
                ),
            ),
        ),
        PaperSubmission.prefetch_latest(lookup="paper__submissions"),
    )


async def prefetch_review(review: Review, request: HttpRequest) -> Review:
    """Refetch a review with all related data prefetched for serialization."""
    qs = with_review_prefetch(Review.objects.all(), request)
    return await qs.aget(pk=review.pk)

from collections import Counter
from urllib.parse import urljoin

from django.db.models import (
    Avg,
    CharField,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Value,
)
from django.http import HttpRequest
from django.urls import reverse
from ninja import Field, Router, Schema
from pydantic import AwareDatetime, HttpUrl

from app.conference.models import (
    AcceptanceLetter,
    Conference,
    Paper,
    PaperFinal,
    PaperSubmission,
    Review,
)
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.types import ConferenceUser
from app.conference.types import Paper as PaperSchema
from app.conference.types import PaperDetailMixin as PaperDetailMixinSchema
from app.conference.types import PaperFinal as PaperFinalSchema
from app.conference.types import PaperSubmission as PaperSubmissionSchema
from app.core.models import User

router = Router(tags=["Paper"], exclude_none=True)


class BasePaperResponse(PaperSchema):
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

    @staticmethod
    def resolve_final(paper: Paper) -> PaperFinalSchema | None:
        latest: PaperFinal | None = next(iter(paper.latest_final), None)  # type: ignore[attr-defined]
        if latest is None:
            return None
        return PaperFinalSchema(
            uid=latest.uid,
            display_name=latest.display_name,
            viewable_display_name=latest.viewable_display_name,
        )


class PaperDetailMixin(PaperDetailMixinSchema):
    @staticmethod
    def resolve_keywords(paper: Paper) -> list[str]:
        return [keyword.text for keyword in paper.keywords.all()]


class UserPaperResponse(BasePaperResponse):
    state: Paper.VisibleState = Field(validation_alias="visible_state")  # type: ignore[assignment]


class UserPaperDetailResponse(PaperDetailMixin, UserPaperResponse):
    pass


class ReviewStat(Schema):
    pending_count: int = 0
    declined_count: int = 0
    accepted_count: int = 0
    submitted_count: int = 0
    cancelled_count: int = 0


class RecommendationSummary(Schema):
    submitted_average: float | None = Field(
        None,
        description="Average recommendation score from submitted reviews.",
    )
    submitted_and_draft_average: float | None = Field(
        None,
        description="Average recommendation score including draft reviews.",
    )


class PaperResponse(BasePaperResponse):
    visible_state: Paper.VisibleState
    announce_time: AwareDatetime | None
    submit_time: AwareDatetime | None
    owner: ConferenceUser
    review_stat: ReviewStat
    recommendation_summary: RecommendationSummary
    labels: dict[str, str]
    acceptance_letter_url: HttpUrl | None

    @staticmethod
    def resolve_acceptance_letter_url(paper: Paper) -> HttpUrl | None:
        if not paper.has_acceptance_letter:  # type: ignore[attr-defined]
            return None
        base_url: str = paper.api_base_url  # type: ignore[attr-defined]
        path = reverse("api-1.0.0:get-acceptance-letter", args=[paper.uid])
        return HttpUrl(urljoin(base_url, path))

    @staticmethod
    def resolve_review_stat(paper: Paper) -> ReviewStat:
        counts = Counter(r.state for r in paper.visible_review_states)  # type: ignore[attr-defined]
        return ReviewStat(
            pending_count=counts[Review.State.PENDING],
            declined_count=counts[Review.State.DECLINED],
            accepted_count=counts[Review.State.ACCEPTED],
            submitted_count=counts[Review.State.SUBMITTED],
            cancelled_count=counts[Review.State.CANCELLED],
        )

    @staticmethod
    def resolve_recommendation_summary(paper: Paper) -> RecommendationSummary:
        return RecommendationSummary(
            submitted_average=paper.submitted_average,  # type: ignore[attr-defined]
            submitted_and_draft_average=paper.submitted_and_draft_average,  # type: ignore[attr-defined]
        )

    @staticmethod
    def resolve_labels(paper: Paper) -> dict[str, str]:
        return {label.key: label.value for label in paper.labels.all()}


class PaperDetailResponse(PaperDetailMixin, PaperResponse):
    pass


async def with_paper_prefetch(
    queryset: QuerySet[Paper],
    conference: Conference,
    user: User,
    request: HttpRequest,
) -> QuerySet[Paper]:
    """Prefetch related data for paper queries."""
    return (
        queryset.select_related(
            "conference",
            "track",
            "owner__profile",
        )
        .annotate(
            submitted_average=Avg(
                "review__recommendation",
                filter=Q(review__state=ReviewState.SUBMITTED),
            ),
            submitted_and_draft_average=Avg(
                "review__recommendation",
                filter=Q(
                    review__state__in=[ReviewState.ACCEPTED, ReviewState.SUBMITTED]
                ),
            ),
            has_acceptance_letter=Exists(
                AcceptanceLetter.objects.filter(paper=OuterRef("pk"))
            ),
            api_base_url=Value(
                request.build_absolute_uri("/"),
                output_field=CharField(),
            ),
        )
        .prefetch_related(
            "authors",
            "labels",
            PaperSubmission.prefetch_latest(),
            PaperFinal.prefetch_latest(),
            Prefetch(
                "reviews",
                queryset=(
                    await ReviewService.visible_reviews(
                        conference=conference,
                        user=user,
                    )
                ).only("state"),
                to_attr="visible_review_states",
            ),
        )
    )


async def prefetch_paper(
    conference: Conference,
    paper: Paper,
    user: User,
    request: HttpRequest,
) -> Paper:
    """Refetch a paper with all related data prefetched for serialization."""
    qs = await with_paper_prefetch(Paper.objects.all(), conference, user, request)
    qs = qs.prefetch_related("keywords")
    return await qs.aget(pk=paper.pk)

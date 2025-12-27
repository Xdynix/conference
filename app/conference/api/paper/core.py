from collections import Counter

from django.db.models import Avg, Prefetch, Q, QuerySet
from ninja import Field, Router, Schema
from pydantic import AwareDatetime

from app.conference.models import Conference, Paper, PaperFinal, PaperSubmission, Review
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


class PaperDetailResponse(PaperDetailMixin, PaperResponse):
    pass


async def with_paper_prefetch(
    queryset: QuerySet[Paper],
    conference: Conference,
    user: User,
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
        )
        .prefetch_related(
            "authors",
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


async def prefetch_paper(conference: Conference, paper: Paper, user: User) -> Paper:
    """Refetch a paper with all related data prefetched for serialization."""
    qs = await with_paper_prefetch(Paper.objects.all(), conference, user)
    qs = qs.prefetch_related("keywords")
    return await qs.aget(pk=paper.pk)

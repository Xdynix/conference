from collections import Counter
from urllib.parse import urljoin

from django.db.models import (
    Avg,
    CharField,
    Count,
    Exists,
    F,
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
    IEEEeCopyrightConsent,
    Paper,
    PaperFinal,
    PaperSubmission,
    PaperVisibleState,
    RegistrationState,
)
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.types import ConferenceUser
from app.conference.types import Paper as PaperSchema
from app.conference.types import PaperDetailMixin as PaperDetailMixinSchema
from app.conference.types import PaperFinal as PaperFinalSchema
from app.conference.types import PaperSubmission as PaperSubmissionSchema
from app.core.models import User
from app.core.types import EmailStr

router = Router(tags=["Paper"], exclude_none=True)


class BasePaperResponse(PaperSchema):
    final_revision_remaining: int

    @staticmethod
    def resolve_conference(paper: Paper) -> str:
        return paper.conference.name

    @staticmethod
    def resolve_final_revision_remaining(paper: Paper) -> int:
        final_count: int = paper.final_count  # type: ignore[attr-defined]
        return max(0, paper.final_revision_limit - final_count)

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

    @staticmethod
    def resolve_final(paper: Paper) -> PaperFinalSchema | None:
        latest: PaperFinal | None = next(iter(paper.latest_final), None)  # type: ignore[attr-defined]
        if latest is None:
            return None
        base_url: str = paper.api_base_url  # type: ignore[attr-defined]
        path = reverse(
            "api-1.0.0:download-final-ex",
            args=[latest.uid, latest.display_name],
        )
        viewable_download_url = None
        if latest.viewable_display_name:
            viewable_path = reverse(
                "api-1.0.0:download-final-viewable-ex",
                args=[latest.uid, latest.viewable_display_name],
            )
            viewable_download_url = HttpUrl(urljoin(base_url, viewable_path))
        return PaperFinalSchema(
            uid=latest.uid,
            display_name=latest.display_name,
            viewable_display_name=latest.viewable_display_name,
            download_url=HttpUrl(urljoin(base_url, path)),
            viewable_download_url=viewable_download_url,
        )


class PaperDetailMixin(PaperDetailMixinSchema):
    @staticmethod
    def resolve_keywords(paper: Paper) -> list[str]:
        return [keyword.text for keyword in paper.keywords.all()]


class UserPaperResponse(BasePaperResponse):
    state: PaperVisibleState = Field(validation_alias="visible_state")  # type: ignore[assignment]


class UserPaperDetailResponse(PaperDetailMixin, UserPaperResponse):
    pass


class ReviewStat(Schema):
    pending_count: int = 0
    declined_count: int = 0
    accepted_count: int = 0
    submitted_count: int = 0
    cancelled_count: int = 0


class RegistrationStat(Schema):
    pending_count: int = 0
    confirmed_count: int = 0


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
    visible_state: PaperVisibleState
    announce_time: AwareDatetime | None
    submit_time: AwareDatetime | None
    owner: ConferenceUser
    final_revision_limit: int
    review_stat: ReviewStat
    registration_stat: RegistrationStat
    recommendation_summary: RecommendationSummary
    labels: dict[str, str]
    acceptance_letter_url: HttpUrl | None
    has_ieee_ecopyright_consent: bool
    claim_email: EmailStr | None

    @staticmethod
    def resolve_acceptance_letter_url(paper: Paper) -> HttpUrl | None:
        if not paper.has_acceptance_letter:  # type: ignore[attr-defined]
            return None
        base_url: str = paper.api_base_url  # type: ignore[attr-defined]
        path = reverse(
            "api-1.0.0:get-acceptance-letter-ex",
            args=[paper.uid, "acceptance-letter.pdf"],
        )
        return HttpUrl(urljoin(base_url, path))

    @staticmethod
    def resolve_review_stat(paper: Paper) -> ReviewStat:
        counts = Counter(r.state for r in paper.visible_review_states)  # type: ignore[attr-defined]
        return ReviewStat(
            pending_count=counts[ReviewState.PENDING],
            declined_count=counts[ReviewState.DECLINED],
            accepted_count=counts[ReviewState.ACCEPTED],
            submitted_count=counts[ReviewState.SUBMITTED],
            cancelled_count=counts[ReviewState.CANCELLED],
        )

    @staticmethod
    def resolve_registration_stat(paper: Paper) -> RegistrationStat:
        return RegistrationStat(
            pending_count=paper.pending_registration_count,  # type: ignore[attr-defined]
            confirmed_count=paper.confirmed_registration_count,  # type: ignore[attr-defined]
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
            claim_email=F("claim__email"),
            has_acceptance_letter=Exists(
                AcceptanceLetter.objects.filter(paper=OuterRef("pk"))
            ),
            has_ieee_ecopyright_consent=Exists(
                IEEEeCopyrightConsent.objects.filter(paper=OuterRef("pk"))
            ),
            final_count=Count("final", distinct=True),
            pending_registration_count=Count(
                "registration",
                filter=Q(registration__state=RegistrationState.PENDING),
                distinct=True,
            ),
            confirmed_registration_count=Count(
                "registration",
                filter=Q(registration__state=RegistrationState.CONFIRMED),
                distinct=True,
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

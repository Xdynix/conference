from django.db.models import F, Prefetch, QuerySet, Window
from django.db.models.functions import RowNumber
from ninja import Field, Router, Schema
from pydantic import AwareDatetime
from ulid import ULID

from app.conference.models import Paper, PaperFinal, PaperSubmission, Profile
from app.conference.types import KeywordText, PaperAbstract, PaperContribution
from app.conference.types import Paper as PaperSchema
from app.conference.types import PaperOwner as BasePaperOwner
from app.core.models import User

router = Router(tags=["Paper"], exclude_none=True)


class PaperSubmissionSchema(Schema):
    uid: ULID
    display_name: str = Field(examples=["PAPER-1001.pdf"])


class PaperFinalSchema(Schema):
    uid: ULID
    display_name: str = Field(examples=["PAPER-1001.zip"])
    viewable_display_name: str | None = Field(examples=["PAPER-1001-viewable.pdf"])


class BasePaperResponse(PaperSchema):
    submission: PaperSubmissionSchema | None
    final: PaperFinalSchema | None

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

    @staticmethod
    def resolve_conference(paper: Paper) -> str:
        return paper.conference.name


class PaperDetailMixin(Schema):
    abstract: PaperAbstract
    contribution: PaperContribution
    keywords: list[KeywordText]

    @staticmethod
    def resolve_keywords(paper: Paper) -> list[str]:
        return [keyword.text for keyword in paper.keywords.all()]


class PaperOwner(BasePaperOwner):
    @staticmethod
    def resolve_profile(user: User) -> Profile | None:
        return getattr(user, "profile", None)


class UserPaperResponse(BasePaperResponse):
    state: Paper.VisibleState = Field(validation_alias="visible_state")  # type: ignore[assignment]


class UserPaperDetailResponse(PaperDetailMixin, UserPaperResponse):
    pass


class PaperResponse(BasePaperResponse):
    visible_state: Paper.VisibleState
    announce_time: AwareDatetime | None
    submit_time: AwareDatetime | None
    decide_time: AwareDatetime | None
    owner: PaperOwner


class PaperDetailResponse(PaperDetailMixin, PaperResponse):
    pass


def with_paper_prefetch(queryset: QuerySet[Paper]) -> QuerySet[Paper]:
    """Prefetch related data for paper queries."""
    latest_submission = (
        PaperSubmission.objects.annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=F("paper"),
                order_by="-revision",
            )
        )
        .filter(row_number=1)
        .select_related("paper")
    )
    latest_final = (
        PaperFinal.objects.annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=F("paper"),
                order_by="-revision",
            )
        )
        .filter(row_number=1)
        .select_related("paper")
    )

    return queryset.select_related(
        "conference",
        "track",
        "owner__profile",
    ).prefetch_related(
        "authors",
        Prefetch(
            "submissions",
            queryset=latest_submission,
            to_attr="latest_submission",
        ),
        Prefetch(
            "finals",
            queryset=latest_final,
            to_attr="latest_final",
        ),
    )


async def prefetch_paper(paper: Paper) -> Paper:
    """Refetch a paper with all related data prefetched for serialization."""
    qs = with_paper_prefetch(Paper.objects.all()).prefetch_related("keywords")
    return await qs.aget(pk=paper.pk)

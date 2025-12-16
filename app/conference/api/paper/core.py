from django.db.models import QuerySet
from ninja import Field, Router, Schema
from pydantic import AwareDatetime

from app.conference.models import Paper, Profile
from app.conference.types import KeywordText, PaperAbstract, PaperContribution
from app.conference.types import Paper as PaperSchema
from app.conference.types import PaperOwner as BasePaperOwner
from app.core.models import User

router = Router(tags=["Paper"], exclude_none=True)


class BasePaperResponse(PaperSchema):
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
    return queryset.select_related(
        "conference",
        "track",
        "owner__profile",
    ).prefetch_related("authors")


async def prefetch_paper(paper: Paper) -> Paper:
    """Refetch a paper with all related data prefetched for serialization."""
    qs = with_paper_prefetch(Paper.objects.all()).prefetch_related("keywords")
    return await qs.aget(pk=paper.pk)

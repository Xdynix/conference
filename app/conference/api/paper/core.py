from django.db.models import QuerySet
from ninja import Field, Router

from app.conference.models import Paper
from app.conference.types import Paper as PaperSchema

router = Router(tags=["Paper"], exclude_none=True)


class BasePaperResponse(PaperSchema):
    @staticmethod
    def resolve_conference(paper: Paper) -> str:
        return paper.conference.name


class UserPaperResponse(BasePaperResponse):
    state: Paper.State = Field(validation_alias="visible_state")


def with_paper_prefetch(queryset: QuerySet[Paper]) -> QuerySet[Paper]:
    """Prefetch related data for paper queries."""
    return queryset.select_related(
        "conference",
        "track",
        "owner__profile",
    ).prefetch_related("authors")

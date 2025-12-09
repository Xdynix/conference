from typing import Any

from ninja import Router, Schema

from app.conference.models import KeywordSet
from app.conference.types import KeywordSetName, KeywordText

router = Router(tags=["Keyword Set"], exclude_none=True)


class KeywordSetSchema(Schema):
    name: KeywordSetName
    keywords: list[KeywordText]

    @staticmethod
    def resolve_keywords(keyword_set: KeywordSet) -> list[str]:
        return [keyword.text for keyword in keyword_set.keywords.all()]


@router.get(
    "/keyword-sets",
    response=list[KeywordSetSchema],
    summary="List Keyword Sets",
    auth=None,  # TODO: Config auth.
)
async def list_keyword_sets(*_: Any) -> list[KeywordSet]:
    """Return all keyword sets and their keywords."""
    keyword_sets = KeywordSet.objects.prefetch_related("keywords")
    return [keyword_set async for keyword_set in keyword_sets]

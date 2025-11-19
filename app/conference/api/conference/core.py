from collections.abc import Collection
from http import HTTPStatus

from django.utils.translation import gettext as _
from ninja import Router
from ninja.errors import HttpError

from app.conference.models import Keyword, KeywordSet

router = Router(tags=["Conference"], exclude_none=True)


def validate_keyword_payload(
    *,
    keyword_texts: Collection[str],
    keyword_set_names: Collection[str],
) -> tuple[list[Keyword], list[KeywordSet]]:
    """Validate keyword lists and return the matching database objects.

    Raise HTTP 422 Unprocessable Entity error if any keywords or keyword sets do not
    exist.
    """
    provided_keywords = set(keyword_texts)
    keywords: list[Keyword] = []
    if provided_keywords:
        keywords = list(Keyword.objects.filter(text__in=provided_keywords))
        missing_keywords = provided_keywords - {keyword.text for keyword in keywords}
        if missing_keywords:
            message = _("Unknown keywords: {keywords}.").format(
                keywords=", ".join(sorted(missing_keywords)),
            )
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    provided_keyword_sets = set(keyword_set_names)
    keyword_sets: list[KeywordSet] = []
    if provided_keyword_sets:
        keyword_sets = list(
            KeywordSet.objects.filter(name__in=provided_keyword_sets).prefetch_related(
                "keywords"
            )
        )
        missing_keyword_sets = provided_keyword_sets - {
            keyword_set.name for keyword_set in keyword_sets
        }
        if missing_keyword_sets:
            message = _("Unknown keyword sets: {keyword_sets}.").format(
                keyword_sets=", ".join(sorted(missing_keyword_sets)),
            )
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    return keywords, keyword_sets

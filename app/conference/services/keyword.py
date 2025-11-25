from collections.abc import Collection
from typing import overload

from django.utils.translation import gettext as _

from app.conference.models import Keyword, KeywordSet


class KeywordService:
    @classmethod
    @overload
    async def validate_keyword_texts(
        cls,
        keyword_texts: Collection[str],
    ) -> Collection[Keyword]: ...

    @classmethod
    @overload
    async def validate_keyword_texts(cls, keyword_texts: None) -> None: ...

    @classmethod
    async def validate_keyword_texts(
        cls,
        keyword_texts: Collection[str] | None,
    ) -> Collection[Keyword] | None:
        """Validates that all provided keyword texts exist in the database.

        Returns ``None`` if the input is ``None``, otherwise returns the corresponding
        ``Keyword`` objects for all provided texts.

        Raises:
            ValueError: If any provided keyword text does not exist in the database.
        """
        if keyword_texts is None:
            return None
        provided = set(keyword_texts)
        if provided:
            keywords = [
                keyword async for keyword in Keyword.objects.filter(text__in=provided)
            ]
        else:
            keywords = []
        missing = provided - {keyword.text for keyword in keywords}
        if missing:
            raise ValueError(
                _("Unknown keywords: {keywords}.").format(
                    keywords=", ".join(sorted(missing))
                )
            )
        return keywords

    @classmethod
    @overload
    async def validate_keyword_set_names(
        cls,
        keyword_set_names: Collection[str],
    ) -> Collection[KeywordSet]: ...

    @classmethod
    @overload
    async def validate_keyword_set_names(cls, keyword_set_names: None) -> None: ...

    @classmethod
    async def validate_keyword_set_names(
        cls,
        keyword_set_names: Collection[str] | None,
    ) -> Collection[KeywordSet] | None:
        """Validates that all provided keyword set names exist in the database.

        Returns ``None`` if the input is ``None``, otherwise returns the corresponding
        ``KeywordSet`` objects for all provided names.

        Raises:
            ValueError: If any provided keyword set name does not exist in the database.
        """
        if keyword_set_names is None:
            return None
        provided = set(keyword_set_names)
        if provided:
            keyword_sets = [
                keyword_set
                async for keyword_set in KeywordSet.objects.filter(name__in=provided)
            ]
        else:
            keyword_sets = []
        missing = provided - {keyword_set.name for keyword_set in keyword_sets}
        if missing:
            raise ValueError(
                _("Unknown keyword sets: {keyword_sets}.").format(
                    keyword_sets=", ".join(sorted(missing))
                )
            )
        return keyword_sets

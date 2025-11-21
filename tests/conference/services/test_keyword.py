import pytest

from app.conference.models import Keyword, KeywordSet
from app.conference.services.keyword import KeywordService


async def create_keywords(*texts: str) -> None:
    for text in texts:
        await Keyword.objects.acreate(text=text)


async def create_keyword_sets(*names: str) -> None:
    for name in names:
        await KeywordSet.objects.acreate(name=name)


@pytest.mark.django_db(transaction=True)
class TestValidateKeywordTexts:
    async def test_returns_none_for_none_input(self) -> None:
        result = await KeywordService.validate_keyword_texts(None)  # type: ignore[func-returns-value]

        assert result is None

    async def test_returns_empty_for_empty_collection(self) -> None:
        result = await KeywordService.validate_keyword_texts([])

        assert result == []

    async def test_happy_path(self) -> None:
        await create_keywords("machine-learning", "deep-learning", "ai")

        result = await KeywordService.validate_keyword_texts(
            ["machine-learning", "deep-learning", "ai"]
        )

        assert len(result) == 3
        result_texts = {k.text for k in result}
        assert result_texts == {"machine-learning", "deep-learning", "ai"}

    async def test_raises_for_missing_keywords(self) -> None:
        await create_keywords("exists")

        with pytest.raises(ValueError, match="Unknown keywords"):
            await KeywordService.validate_keyword_texts(["exists", "missing"])

    async def test_raises_for_multiple_missing_keywords(self) -> None:
        await create_keywords("exists")

        with pytest.raises(ValueError, match="Unknown keywords") as exc_info:
            await KeywordService.validate_keyword_texts(
                ["exists", "missing1", "missing2"],
            )

        msg = str(exc_info.value)
        assert "missing1" in msg
        assert "missing2" in msg


@pytest.mark.django_db(transaction=True)
class TestValidateKeywordSetNames:
    async def test_returns_none_for_none_input(self) -> None:
        result = await KeywordService.validate_keyword_set_names(None)  # type: ignore[func-returns-value]

        assert result is None

    async def test_returns_empty_for_empty_collection(self) -> None:
        result = await KeywordService.validate_keyword_set_names([])

        assert result == []

    async def test_happy_path(self) -> None:
        await create_keyword_sets("topics", "domains", "categories")

        result = await KeywordService.validate_keyword_set_names(
            ["topics", "domains", "categories"]
        )

        assert len(result) == 3
        result_names = {ks.name for ks in result}
        assert result_names == {"topics", "domains", "categories"}

    async def test_raises_for_missing_keyword_sets(self) -> None:
        await create_keyword_sets("exists")

        with pytest.raises(ValueError, match="Unknown keyword sets"):
            await KeywordService.validate_keyword_set_names(["exists", "missing"])

    async def test_raises_for_multiple_missing_keyword_sets(self) -> None:
        await create_keyword_sets("exists")

        with pytest.raises(ValueError, match="Unknown keyword sets") as exc_info:
            await KeywordService.validate_keyword_set_names(
                ["exists", "missing1", "missing2"]
            )

        msg = str(exc_info.value)
        assert "missing1" in msg
        assert "missing2" in msg

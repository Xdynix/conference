from app.conference.models import Keyword, KeywordSet


class TestKeyword:
    def test_str(self) -> None:
        assert str(Keyword(text="Foobar")) == "Foobar"


class TestKeywordSet:
    def test_str(self) -> None:
        assert str(KeywordSet(name="Foobar")) == "Foobar"

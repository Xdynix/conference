import pytest

from app.conference.models import Conference, Keyword, Paper, Track
from app.conference.services import PaperService
from app.core.models import User


@pytest.mark.django_db
class TestPaperServiceSetPaperKeywords:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
        )

    def test_sets_keywords(self, paper: Paper) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")

        PaperService.set_paper_keywords(paper, [kw1, kw2])

        assert set(paper.keywords.all()) == {kw1, kw2}

    def test_replaces_existing_keywords(self, paper: Paper) -> None:
        old_kw = Keyword.objects.create(text="Old Keyword")
        new_kw = Keyword.objects.create(text="New Keyword")
        paper.keywords.add(old_kw)

        PaperService.set_paper_keywords(paper, [new_kw])

        assert list(paper.keywords.all()) == [new_kw]

    def test_clears_keywords_with_empty_collection(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.set_paper_keywords(paper, [])

        assert not paper.keywords.exists()

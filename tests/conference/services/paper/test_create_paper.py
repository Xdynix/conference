import pytest

from app.conference.models import Conference, Keyword, Paper, Track
from app.conference.services import PaperService
from app.conference.services.paper import AuthorData, NoCodePoolError
from app.core.models import User


@pytest.mark.django_db
class TestPaperServiceCreatePaper:
    def test_happy_path(
        self,
        user: User,
        conference: Conference,
        track_with_pool: Track,
    ) -> None:
        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            title="Test Paper",
            abstract="Test abstract",
            contribution="Test contribution",
        )

        db_paper = Paper.objects.get(pk=paper.pk)
        assert paper == db_paper
        assert paper.conference == db_paper.conference == conference
        assert paper.track == db_paper.track == track_with_pool
        assert paper.owner == db_paper.owner == user
        assert paper.title == db_paper.title == "Test Paper"
        assert paper.abstract == db_paper.abstract == "Test abstract"
        assert paper.contribution == db_paper.contribution == "Test contribution"
        assert paper.state == db_paper.state == Paper.State.DRAFT
        assert paper.code == db_paper.code == "TEST-001"

    def test_generates_sequential_codes(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        paper1 = PaperService.create_paper(track=track_with_pool, owner=user)
        paper2 = PaperService.create_paper(track=track_with_pool, owner=user)
        paper3 = PaperService.create_paper(track=track_with_pool, owner=user)

        assert paper1.code == "TEST-001"
        assert paper2.code == "TEST-002"
        assert paper3.code == "TEST-003"

    def test_defaults_to_empty_strings(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        paper = PaperService.create_paper(track=track_with_pool, owner=user)

        assert paper.title == ""
        assert paper.abstract == ""
        assert paper.contribution == ""

    def test_raises_when_track_has_no_code_pool(
        self,
        user: User,
        track: Track,
    ) -> None:
        with pytest.raises(NoCodePoolError):
            PaperService.create_paper(track=track, owner=user)

        assert not Paper.objects.exists()

    def test_with_keywords(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")

        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            keywords=[kw1, kw2],
        )

        assert set(paper.keywords.all()) == {kw1, kw2}

    def test_with_authors(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        authors: list[AuthorData] = [
            {
                "given_name": "Alice",
                "family_name": "Smith",
                "email": "alice@example.com",
                "corresponding": True,
            },
            {
                "given_name": "Bob",
                "family_name": "Jones",
                "affiliation": "University",
            },
        ]

        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            authors=authors,
        )

        [author0, author1] = list(paper.authors.all())

        assert author0.given_name == "Alice"
        assert author0.family_name == "Smith"
        assert author0.email == "alice@example.com"
        assert author0.corresponding is True
        assert author0.ordering == 0

        assert author1.given_name == "Bob"
        assert author1.family_name == "Jones"
        assert author1.affiliation == "University"
        assert author1.corresponding is False
        assert author1.ordering == 1

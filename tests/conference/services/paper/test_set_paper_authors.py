import pytest

from app.conference.models import Conference, Paper, PaperAuthor, Track
from app.conference.services import PaperService
from app.conference.services.paper import AuthorData
from app.core.models import User


@pytest.mark.django_db
class TestPaperServiceSetPaperAuthors:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
        )

    def test_sets_authors_with_ordering(self, paper: Paper) -> None:
        authors: list[AuthorData] = [
            {"given_name": "First", "family_name": "Author"},
            {"given_name": "Second", "family_name": "Author"},
            {"given_name": "Third", "family_name": "Author"},
        ]

        PaperService.set_paper_authors(paper, authors)

        db_authors = list(paper.authors.order_by("ordering"))
        assert len(db_authors) == 3
        assert db_authors[0].given_name == "First"
        assert db_authors[0].ordering == 0
        assert db_authors[1].given_name == "Second"
        assert db_authors[1].ordering == 1
        assert db_authors[2].given_name == "Third"
        assert db_authors[2].ordering == 2

    def test_sets_all_author_fields(self, paper: Paper) -> None:
        authors: list[AuthorData] = [
            {
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "MIT",
                "region_code": "US",
                "email": "alice@mit.edu",
                "phone": "+1234567890",
                "corresponding": True,
            },
        ]

        PaperService.set_paper_authors(paper, authors)

        author = paper.authors.get()
        assert author.given_name == "Alice"
        assert author.family_name == "Smith"
        assert author.affiliation == "MIT"
        assert author.region_code == "US"
        assert author.email == "alice@mit.edu"
        assert author.phone == "+1234567890"
        assert author.corresponding is True

    def test_defaults_missing_fields(self, paper: Paper) -> None:
        authors: list[AuthorData] = [{"given_name": "Alice"}]

        PaperService.set_paper_authors(paper, authors)

        author = paper.authors.get()
        assert author.given_name == "Alice"
        assert author.family_name == ""
        assert author.affiliation == ""
        assert author.region_code == ""
        assert author.email == ""
        assert author.phone == ""
        assert author.corresponding is False

    def test_replaces_existing_authors(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Old",
            family_name="Author",
        )
        authors: list[AuthorData] = [{"given_name": "New", "family_name": "Author"}]

        PaperService.set_paper_authors(paper, authors)

        assert paper.authors.count() == 1
        assert paper.authors.get().given_name == "New"

    def test_clears_authors_with_empty_collection(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Existing",
            family_name="Author",
        )

        PaperService.set_paper_authors(paper, [])

        assert not paper.authors.exists()

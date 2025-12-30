import pytest
from django.utils import timezone

from app.conference.models import (
    Conference,
    Keyword,
    Paper,
    PaperAuthor,
    PaperState,
    Track,
)
from app.conference.services import PaperService
from app.conference.services.paper import (
    AuthorData,
    PaperStateError,
    PaperWithdrawnError,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceUpdatePaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Original Title",
            abstract="Original abstract",
            contribution="Original contribution",
        )

    def test_happy_path(self, paper: Paper) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")
        authors: list[AuthorData] = [
            {"given_name": "Alice", "family_name": "Smith"},
            {"given_name": "Bob", "family_name": "Jones"},
        ]

        updated = PaperService.update_paper(
            paper=paper,
            title="Updated Title",
            abstract="Updated abstract",
            contribution="Updated contribution",
            keywords=[kw1, kw2],
            authors=authors,
            mode="author",
        )

        db_updated = Paper.objects.get(pk=paper.pk)
        assert updated == db_updated
        assert updated.title == db_updated.title == "Updated Title"
        assert updated.abstract == db_updated.abstract == "Updated abstract"
        assert updated.contribution == db_updated.contribution == "Updated contribution"
        assert set(updated.keywords.all()) == {kw1, kw2}
        assert updated.authors.count() == 2

    def test_update_title_only(self, paper: Paper) -> None:
        PaperService.update_paper(paper=paper, title="New Title", mode="author")

        paper.refresh_from_db()
        assert paper.title == "New Title"
        assert paper.abstract == "Original abstract"
        assert paper.contribution == "Original contribution"

    def test_update_abstract_only(self, paper: Paper) -> None:
        PaperService.update_paper(paper=paper, abstract="New abstract", mode="author")

        paper.refresh_from_db()
        assert paper.title == "Original Title"
        assert paper.abstract == "New abstract"
        assert paper.contribution == "Original contribution"

    def test_update_contribution_only(self, paper: Paper) -> None:
        PaperService.update_paper(
            paper=paper, contribution="New contribution", mode="author"
        )

        paper.refresh_from_db()
        assert paper.title == "Original Title"
        assert paper.abstract == "Original abstract"
        assert paper.contribution == "New contribution"

    def test_set_fields_to_empty_string(self, paper: Paper) -> None:
        PaperService.update_paper(
            paper=paper,
            title="",
            abstract="",
            contribution="",
            mode="author",
        )

        paper.refresh_from_db()
        assert paper.title == ""
        assert paper.abstract == ""
        assert paper.contribution == ""

    def test_update_keywords_replaces_all(self, paper: Paper) -> None:
        old_kw = Keyword.objects.create(text="Old Keyword")
        new_kw1 = Keyword.objects.create(text="New Keyword 1")
        new_kw2 = Keyword.objects.create(text="New Keyword 2")
        paper.keywords.add(old_kw)

        PaperService.update_paper(
            paper=paper,
            keywords=[new_kw1, new_kw2],
            mode="author",
        )

        assert set(paper.keywords.all()) == {new_kw1, new_kw2}

    def test_update_keywords_clears_with_empty_collection(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.update_paper(paper=paper, keywords=[], mode="author")

        assert not paper.keywords.exists()

    def test_omit_keywords_keeps_existing(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.update_paper(paper=paper, title="New Title", mode="author")

        assert list(paper.keywords.all()) == [kw]

    def test_update_authors_replaces_all(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Old",
            family_name="Author",
        )
        new_authors: list[AuthorData] = [
            {"given_name": "Alice", "family_name": "Smith"},
            {"given_name": "Bob", "family_name": "Jones"},
        ]

        PaperService.update_paper(paper=paper, authors=new_authors, mode="author")

        [author0, author1] = list(paper.authors.all())
        assert author0.given_name == "Alice"
        assert author0.ordering == 0
        assert author1.given_name == "Bob"
        assert author1.ordering == 1

    def test_update_authors_clears_with_empty_collection(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Existing",
            family_name="Author",
        )

        PaperService.update_paper(paper=paper, authors=[], mode="author")

        assert not paper.authors.exists()

    def test_raises_when_paper_is_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(PaperWithdrawnError) as exc_info:
            PaperService.update_paper(paper=paper, title="Should fail", mode="author")

        assert str(exc_info.value) == "Withdrawn papers cannot be updated."

        paper.refresh_from_db()
        assert paper.title == "Original Title"

    @pytest.mark.parametrize(
        "state",
        [state for state in PaperState if state != PaperState.DRAFT],
    )
    def test_author_mode_rejects_non_draft_state(
        self, paper: Paper, state: PaperState
    ) -> None:
        update_object(paper, state=state)

        with pytest.raises(PaperStateError) as exc_info:
            PaperService.update_paper(paper=paper, mode="author", title="Should fail")

        assert str(exc_info.value) == "Paper must be in Draft state to update."

        paper.refresh_from_db()
        assert paper.title == "Original Title"

    @pytest.mark.parametrize("state", PaperState.decided())
    def test_track_admin_mode_rejects_decided_state(
        self, paper: Paper, state: PaperState
    ) -> None:
        update_object(paper, state=state)

        with pytest.raises(PaperStateError) as exc_info:
            PaperService.update_paper(
                paper=paper, mode="track_admin", title="Should fail"
            )

        assert (
            str(exc_info.value)
            == "Only conference admins can update papers after decision."
        )

        paper.refresh_from_db()
        assert paper.title == "Original Title"

    @pytest.mark.parametrize(
        "state",
        [state for state in PaperState if state not in PaperState.decided()],
    )
    def test_track_admin_mode_allows_non_decided_state(
        self, paper: Paper, state: PaperState
    ) -> None:
        update_object(paper, state=state)

        updated = PaperService.update_paper(
            paper=paper, mode="track_admin", title="Updated Title"
        )

        assert updated.title == "Updated Title"

    @pytest.mark.parametrize("state", PaperState)
    def test_admin_mode_allows_any_state(self, paper: Paper, state: PaperState) -> None:
        update_object(paper, state=state)

        updated = PaperService.update_paper(
            paper=paper, mode="admin", title="Updated Title"
        )

        assert updated.title == "Updated Title"

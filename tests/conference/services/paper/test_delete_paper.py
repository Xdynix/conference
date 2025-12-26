import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError, PaperWithdrawnError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceDeletePaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

    def test_happy_path(self, paper: Paper) -> None:
        deleted = PaperService.delete_paper(paper=paper, mode="author")

        db_deleted = Paper.objects.get(pk=deleted.pk)
        assert deleted.delete_time == db_deleted.delete_time is not None

    def test_raises_when_paper_is_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be deleted",
        ):
            PaperService.delete_paper(paper=paper, mode="author")

        paper.refresh_from_db()
        assert paper.delete_time is None

    @pytest.mark.parametrize(
        "state",
        [
            Paper.State.UNDER_REVIEW,
            Paper.State.REJECTED,
            Paper.State.ACCEPTED,
            Paper.State.ACCEPTED_REVISION_NEEDED,
        ],
    )
    def test_author_mode_rejects_non_deletable_state(
        self,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)

        with pytest.raises(
            PaperStateError,
            match="Paper must be in Draft or Submitted state to delete",
        ):
            PaperService.delete_paper(paper=paper, mode="author")

        paper.refresh_from_db()
        assert paper.delete_time is None

    @pytest.mark.parametrize("state", [Paper.State.DRAFT, Paper.State.SUBMITTED])
    def test_author_mode_allows_draft_and_submitted(
        self, paper: Paper, state: Paper.State
    ) -> None:
        update_object(paper, state=state)

        deleted = PaperService.delete_paper(paper=paper, mode="author")

        assert deleted.delete_time is not None

    @pytest.mark.parametrize("state", Paper.State.decided())
    def test_track_admin_mode_rejects_decided_state(
        self, paper: Paper, state: Paper.State
    ) -> None:
        update_object(paper, state=state)

        with pytest.raises(
            PaperStateError,
            match=(
                "Track admins can only delete papers in Draft, Submitted, "
                "or Under Review state"
            ),
        ):
            PaperService.delete_paper(paper=paper, mode="track_admin")

        paper.refresh_from_db()
        assert paper.delete_time is None

    @pytest.mark.parametrize(
        "state",
        [state for state in Paper.State if state not in Paper.State.decided()],
    )
    def test_track_admin_mode_allows_non_decided_state(
        self, paper: Paper, state: Paper.State
    ) -> None:
        update_object(paper, state=state)

        deleted = PaperService.delete_paper(paper=paper, mode="track_admin")

        assert deleted.delete_time is not None

    @pytest.mark.parametrize("state", Paper.State)
    def test_admin_mode_allows_any_state(
        self, paper: Paper, state: Paper.State
    ) -> None:
        update_object(paper, state=state)

        deleted = PaperService.delete_paper(paper=paper, mode="admin")

        assert deleted.delete_time is not None

import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError, PaperWithdrawnError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceUnsubmitPaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper Title",
            state=Paper.State.SUBMITTED,
            submit_time=timezone.now(),
        )

    def test_happy_path(self, paper: Paper) -> None:
        unsubmitted = PaperService.unsubmit_paper(paper)

        db_unsubmitted = Paper.objects.get(pk=unsubmitted.pk)
        assert unsubmitted.state == db_unsubmitted.state == Paper.State.DRAFT
        assert unsubmitted.submit_time == db_unsubmitted.submit_time is None

    def test_raises_when_paper_is_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be unsubmitted",
        ):
            PaperService.unsubmit_paper(paper)

        paper.refresh_from_db()
        assert paper.state == Paper.State.SUBMITTED
        assert paper.submit_time is not None

    def test_withdrawn_paper_reports_withdrawn_even_when_not_submitted(
        self,
        paper: Paper,
    ) -> None:
        update_object(paper, state=Paper.State.DRAFT, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be unsubmitted",
        ):
            PaperService.unsubmit_paper(paper)

    @pytest.mark.parametrize(
        "state",
        [state for state in Paper.State if state != Paper.State.SUBMITTED],
    )
    def test_rejects_non_submitted_state(
        self,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)

        with pytest.raises(
            PaperStateError,
            match="Paper must be in Submitted state to unsubmit",
        ):
            PaperService.unsubmit_paper(paper)

    def test_raises_when_paper_deleted(self, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.unsubmit_paper(paper)

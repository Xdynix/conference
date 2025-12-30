import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, PaperState, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperWithdrawnError
from app.core.models import User
from tests.helpers import approx_now, update_object


@pytest.mark.django_db
class TestPaperServiceWithdrawPaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper Title",
        )

    def test_happy_path(self, paper: Paper) -> None:
        withdrawn = PaperService.withdraw_paper(paper)

        db_withdrawn = Paper.objects.get(pk=withdrawn.pk)
        assert withdrawn.withdraw_time == db_withdrawn.withdraw_time == approx_now()

    def test_raises_when_already_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Paper has already been withdrawn",
        ):
            PaperService.withdraw_paper(paper)

    def test_raises_when_paper_deleted(self, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.withdraw_paper(paper)

    @pytest.mark.parametrize("state", PaperState)
    def test_can_withdraw_from_any_state(
        self,
        paper: Paper,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)

        withdrawn = PaperService.withdraw_paper(paper)

        assert withdrawn.withdraw_time == approx_now()
        assert withdrawn.state == state

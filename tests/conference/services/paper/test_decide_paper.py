import pytest
from django.utils import timezone

from app.conference.models import (
    Conference,
    Paper,
    PaperDecision,
    PaperDecisionState,
    PaperState,
    Track,
)
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError, PaperWithdrawnError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceDecidePaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper Title",
            state=PaperState.SUBMITTED,
        )

    def test_happy_path(self, user: User, paper: Paper) -> None:
        decided = PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=PaperState.ACCEPTED,
            note="Strong contribution.",
        )

        db_paper = Paper.objects.get(pk=paper.pk)
        assert decided.state == db_paper.state == PaperState.ACCEPTED

        decision = PaperDecision.objects.get(paper=paper)
        assert decision.decider == user
        assert decision.state == PaperDecisionState.ACCEPTED
        assert decision.note == "Strong contribution."

    def test_creates_decision_record_with_empty_note(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=PaperState.REJECTED,
        )

        decision = PaperDecision.objects.get(paper=paper)
        assert decision.state == PaperDecisionState.REJECTED
        assert decision.note == ""

    def test_raises_when_paper_is_draft(self, user: User, paper: Paper) -> None:
        update_object(paper, state=PaperState.DRAFT)

        with pytest.raises(
            PaperStateError,
            match="Draft papers cannot be decided",
        ):
            PaperService.decide_paper(
                paper=paper,
                decider=user,
                state=PaperState.ACCEPTED,
            )

        paper.refresh_from_db()
        assert paper.state == PaperState.DRAFT
        assert not PaperDecision.objects.filter(paper=paper).exists()

    def test_raises_when_paper_is_withdrawn(self, user: User, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be decided",
        ):
            PaperService.decide_paper(
                paper=paper,
                decider=user,
                state=PaperState.ACCEPTED,
            )

        assert not PaperDecision.objects.filter(paper=paper).exists()

    def test_raises_when_paper_is_deleted(self, user: User, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.decide_paper(
                paper=paper,
                decider=user,
                state=PaperState.ACCEPTED,
            )

    @pytest.mark.parametrize(
        "invalid_state",
        [state for state in PaperState if state not in PaperState.decided()],
    )
    def test_raises_on_invalid_decision_state(
        self,
        user: User,
        paper: Paper,
        invalid_state: PaperState,
    ) -> None:
        with pytest.raises(ValueError, match="Invalid decision state"):
            PaperService.decide_paper(
                paper=paper,
                decider=user,
                state=invalid_state,
            )

    @pytest.mark.parametrize(
        "initial_state",
        [state for state in PaperState if state != PaperState.DRAFT],
    )
    def test_can_decide_from_non_draft_states(
        self,
        user: User,
        paper: Paper,
        initial_state: PaperState,
    ) -> None:
        update_object(paper, state=initial_state)

        decided = PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=PaperState.ACCEPTED,
        )

        assert decided.state == PaperState.ACCEPTED
        assert PaperDecision.objects.filter(paper=paper).count() == 1

    def test_can_change_previous_decision(self, user: User, paper: Paper) -> None:
        PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=PaperState.REJECTED,
            note="Initial rejection.",
        )

        PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=PaperState.ACCEPTED,
            note="Reconsidered after discussion.",
        )

        paper.refresh_from_db()
        assert paper.state == PaperState.ACCEPTED
        assert PaperDecision.objects.filter(paper=paper).count() == 2

        [decision1, decision2] = paper.decisions.order_by("create_time")
        assert decision1.state == PaperDecisionState.REJECTED
        assert decision2.state == PaperDecisionState.ACCEPTED

    @pytest.mark.parametrize(
        "decision_state",
        PaperState.decided(),
    )
    def test_all_valid_decision_states(
        self,
        user: User,
        paper: Paper,
        decision_state: PaperState,
    ) -> None:
        decided = PaperService.decide_paper(
            paper=paper,
            decider=user,
            state=decision_state,
        )

        assert decided.state == decision_state

        decision = PaperDecision.objects.get(paper=paper)
        assert decision.state == PaperDecisionState(decision_state)

import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import AcceptanceLetter, Conference, Paper, PaperState, Track
from app.conference.services import PaperService
from app.core.models import User
from tests.helpers import a_update_object


@pytest.mark.django_db(transaction=True)
class TestPaperServiceAnnouncePapers:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
            state=PaperState.REJECTED,
        )

    async def test_announces_rejected_paper(
        self,
        conference: Conference,
        paper: Paper,
    ) -> None:
        result = await PaperService.announce_papers(conference, ["PAPER-001"])

        assert result == ["PAPER-001"]

        await paper.arefresh_from_db()
        assert paper.announce_time is not None

    @pytest.mark.parametrize(
        "state",
        [PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED],
    )
    async def test_announces_accepted_with_letter(
        self,
        conference: Conference,
        paper: Paper,
        state: PaperState,
    ) -> None:
        await a_update_object(paper, state=state)
        await AcceptanceLetter.objects.acreate(
            paper=paper,
            rendered_pdf="fake.pdf",
            template="Congrats!",
            context={},
        )

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == ["PAPER-001"]

        await paper.arefresh_from_db()
        assert paper.announce_time is not None

    async def test_announces_multiple_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-A",
            title="Paper A",
            state=PaperState.REJECTED,
        )
        paper_b = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-B",
            title="Paper B",
            state=PaperState.ACCEPTED,
        )
        await AcceptanceLetter.objects.acreate(
            paper=paper_b,
            rendered_pdf="fake.pdf",
            template="Yes!",
            context={},
        )

        result = await PaperService.announce_papers(conference, ["PAPER-A", "PAPER-B"])
        assert result == ["PAPER-A", "PAPER-B"]

        await paper_a.arefresh_from_db()
        await paper_b.arefresh_from_db()
        assert paper_a.announce_time is not None
        assert paper_b.announce_time is not None

    async def test_empty_list_returns_empty(self, conference: Conference) -> None:
        result = await PaperService.announce_papers(conference, [])

        assert result == []

    async def test_skips_paper_without_decision(
        self,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await a_update_object(paper, state=PaperState.SUBMITTED)

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == []

        await paper.arefresh_from_db()
        assert paper.announce_time is None

    @pytest.mark.parametrize(
        "state",
        [PaperState.DRAFT, PaperState.SUBMITTED, PaperState.UNDER_REVIEW],
    )
    async def test_skips_non_decided_states(
        self,
        conference: Conference,
        paper: Paper,
        state: PaperState,
    ) -> None:
        await a_update_object(paper, state=state)

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == []

    async def test_skips_withdrawn_paper(
        self,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await a_update_object(paper, withdraw_time=timezone.now())

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == []

        await paper.arefresh_from_db()
        assert paper.announce_time is None

    async def test_skips_already_announced_paper(
        self,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await a_update_object(paper, announce_time=timezone.now())

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == []

    @pytest.mark.parametrize(
        "state",
        [PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED],
    )
    async def test_skips_accepted_without_letter(
        self,
        conference: Conference,
        paper: Paper,
        state: PaperState,
    ) -> None:
        await a_update_object(paper, state=state)

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == []

        await paper.arefresh_from_db()
        assert paper.announce_time is None

    async def test_rejected_does_not_require_letter(
        self,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await a_update_object(paper, state=PaperState.REJECTED)

        result = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result == ["PAPER-001"]

    async def test_nonexistent_code_ignored(
        self,
        conference: Conference,
        paper: Paper,  # noqa: ARG002
    ) -> None:
        result = await PaperService.announce_papers(
            conference, ["PAPER-001", "NONEXISTENT"]
        )
        assert result == ["PAPER-001"]

    async def test_paper_from_different_conference_ignored(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        paper: Paper,  # noqa: ARG002
    ) -> None:
        other_conference = await Conference.objects.acreate(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = await Track.objects.acreate(
            conference=other_conference,
            display_name=faker.word(),
        )
        await Paper.objects.acreate(
            conference=other_conference,
            track=other_track,
            owner=user,
            code="OTHER-PAPER",
            title="Other Paper",
            state=PaperState.REJECTED,
        )

        result = await PaperService.announce_papers(
            conference, ["PAPER-001", "OTHER-PAPER"]
        )
        assert result == ["PAPER-001"]

    async def test_mixed_eligible_and_ineligible(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        rejected = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="REJECTED",
            title=faker.sentence(),
            state=PaperState.REJECTED,
        )
        accepted_with_letter = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="ACCEPTED",
            title=faker.sentence(),
            state=PaperState.ACCEPTED,
        )
        await AcceptanceLetter.objects.acreate(
            paper=accepted_with_letter,
            rendered_pdf="fake.pdf",
            template="Yes!",
            context={},
        )
        accepted_no_letter = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="NO-LETTER",
            title=faker.sentence(),
            state=PaperState.ACCEPTED,
        )
        no_decision = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="NO-DECISION",
            title=faker.sentence(),
            state=PaperState.SUBMITTED,
        )
        withdrawn = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="WITHDRAWN",
            title=faker.sentence(),
            state=PaperState.REJECTED,
            withdraw_time=timezone.now(),
        )

        result = await PaperService.announce_papers(
            conference,
            ["REJECTED", "ACCEPTED", "NO-LETTER", "NO-DECISION", "WITHDRAWN"],
        )
        assert result == ["ACCEPTED", "REJECTED"]

        await rejected.arefresh_from_db()
        await accepted_with_letter.arefresh_from_db()
        await accepted_no_letter.arefresh_from_db()
        await no_decision.arefresh_from_db()
        await withdrawn.arefresh_from_db()

        assert rejected.announce_time is not None
        assert accepted_with_letter.announce_time is not None
        assert accepted_no_letter.announce_time is None
        assert no_decision.announce_time is None
        assert withdrawn.announce_time is None

    async def test_idempotent_when_called_twice(
        self,
        conference: Conference,
        paper: Paper,  # noqa: ARG002
    ) -> None:
        result1 = await PaperService.announce_papers(conference, ["PAPER-001"])
        result2 = await PaperService.announce_papers(conference, ["PAPER-001"])
        assert result1 == ["PAPER-001"]
        assert result2 == []

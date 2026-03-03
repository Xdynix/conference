import pytest
from django.db import IntegrityError
from faker import Faker

from app.conference.models import (
    Conference,
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateMatchType,
    DuplicateReport,
    DuplicateReportState,
    Paper,
    Track,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper(faker: Faker, user: User, conference: Conference, track: Track) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        code=faker.lexify(text="????-###"),
        owner=user,
        title=faker.sentence(),
    )


@pytest.fixture
def report() -> DuplicateReport:
    return DuplicateReport.objects.create()


@pytest.fixture
def two_papers(
    faker: Faker,
    user: User,
    conference: Conference,
    track: Track,
) -> tuple[Paper, Paper]:
    paper_a = Paper.objects.create(
        conference=conference,
        track=track,
        code="PAPER-001",
        owner=user,
        title=faker.sentence(),
    )
    paper_b = Paper.objects.create(
        conference=conference,
        track=track,
        code="PAPER-002",
        owner=user,
        title=faker.sentence(),
    )
    return paper_a, paper_b


@pytest.mark.django_db
class TestDuplicateReport:
    @pytest.mark.parametrize("state", DuplicateReportState)
    def test_str(self, report: DuplicateReport, state: DuplicateReportState) -> None:
        update_object(report, state=state)
        assert str(report) == f"DuplicateReport {report.pk} ({report.state})"


@pytest.mark.django_db
class TestDuplicateMatch:
    def test_str(
        self,
        report: DuplicateReport,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        match = DuplicateMatch(
            report=report,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.FILE_HASH,
            score=1.0,
        )
        assert str(match) == (
            f"{paper_a.pk}-{paper_b.pk} ({DuplicateMatchType.FILE_HASH})"
        )

    def test_paper_a_before_b_constraint(
        self,
        report: DuplicateReport,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        with pytest.raises(IntegrityError):
            DuplicateMatch.objects.create(
                report=report,
                paper_a=paper_b,
                paper_b=paper_a,
                match_type=DuplicateMatchType.FILE_HASH,
                score=1.0,
            )

    def test_unique_report_pair_type(
        self,
        report: DuplicateReport,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        DuplicateMatch.objects.create(
            report=report,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.FILE_HASH,
            score=1.0,
        )

        with pytest.raises(IntegrityError):
            DuplicateMatch.objects.create(
                report=report,
                paper_a=paper_a,
                paper_b=paper_b,
                match_type=DuplicateMatchType.FILE_HASH,
                score=0.9,
            )

    def test_same_pair_different_report(self, two_papers: tuple[Paper, Paper]) -> None:
        paper_a, paper_b = two_papers
        report1 = DuplicateReport.objects.create()
        report2 = DuplicateReport.objects.create()
        DuplicateMatch.objects.create(
            report=report1,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.FILE_HASH,
            score=1.0,
        )
        DuplicateMatch.objects.create(
            report=report2,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.FILE_HASH,
            score=1.0,
        )

    def test_same_pair_different_match_type(
        self,
        report: DuplicateReport,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        DuplicateMatch.objects.create(
            report=report,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.FILE_HASH,
            score=1.0,
        )
        DuplicateMatch.objects.create(
            report=report,
            paper_a=paper_a,
            paper_b=paper_b,
            match_type=DuplicateMatchType.TITLE_SIMILARITY,
            score=0.85,
        )


@pytest.mark.django_db
class TestDuplicateAcknowledgment:
    def test_str(
        self,
        user: User,
        conference: Conference,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        ack = DuplicateAcknowledgment(
            paper_a=paper_a,
            paper_b=paper_b,
            conference=conference,
            user=user,
        )
        assert str(ack) == f"[{conference}] {paper_a.pk}-{paper_b.pk}"

    def test_paper_a_before_b_constraint(
        self,
        user: User,
        conference: Conference,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        with pytest.raises(IntegrityError):
            DuplicateAcknowledgment.objects.create(
                paper_a=paper_b,
                paper_b=paper_a,
                conference=conference,
                user=user,
            )

    def test_unique_per_conference(
        self,
        user: User,
        conference: Conference,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        DuplicateAcknowledgment.objects.create(
            paper_a=paper_a,
            paper_b=paper_b,
            conference=conference,
            user=user,
        )
        with pytest.raises(IntegrityError):
            DuplicateAcknowledgment.objects.create(
                paper_a=paper_a,
                paper_b=paper_b,
                conference=conference,
                user=user,
                note="duplicate",
            )

    def test_different_conferences_same_pair(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        two_papers: tuple[Paper, Paper],
    ) -> None:
        paper_a, paper_b = two_papers
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=conference.visibility,
        )
        DuplicateAcknowledgment.objects.create(
            paper_a=paper_a,
            paper_b=paper_b,
            conference=conference,
            user=user,
        )
        DuplicateAcknowledgment.objects.create(
            paper_a=paper_a,
            paper_b=paper_b,
            conference=other_conference,
            user=user,
        )

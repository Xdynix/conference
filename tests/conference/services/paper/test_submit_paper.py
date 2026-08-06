from typing import Any

import pytest
from django.core.mail import EmailMessage
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    Keyword,
    Paper,
    PaperAuthor,
    PaperState,
    PaperSubmission,
    Track,
)
from app.conference.services import PaperService
from app.conference.services.paper import (
    PaperStateError,
    PaperSubmissionError,
    PaperWithdrawnError,
)
from app.core.models import User
from tests.helpers import approx_now, update_object


@pytest.mark.django_db
class TestPaperServiceSubmitPaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper Title",
            abstract="Test abstract",
            contribution="Test contribution",
        )

    @classmethod
    def add_keywords(cls, paper: Paper) -> None:
        k1 = Keyword.objects.create(text="Machine Learning")
        k2 = Keyword.objects.create(text="Deep Learning")
        paper.keywords.add(k1, k2)

    @classmethod
    def add_author(
        cls,
        paper: Paper,
        ordering: int = 0,
        *,
        given_name: str = "Alice",
        family_name: str = "Smith",
        affiliation: str = "University",
        region_code: str = "US",
        email: str = "alice@example.com",
        corresponding: bool = False,
    ) -> PaperAuthor:
        return PaperAuthor.objects.create(
            paper=paper,
            ordering=ordering,
            given_name=given_name,
            family_name=family_name,
            affiliation=affiliation,
            region_code=region_code,
            email=email,
            corresponding=corresponding,
        )

    @classmethod
    def add_submission(cls, paper: Paper, user: User) -> None:
        PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="test.pdf",
            uploader=user,
        )

    def test_happy_path(self, user: User, paper: Paper) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)

        submitted = PaperService.submit_paper(paper)

        db_submitted = Paper.objects.get(pk=submitted.pk)
        assert submitted.state == db_submitted.state == PaperState.SUBMITTED
        assert submitted.submit_time == db_submitted.submit_time == approx_now()

    def test_non_strict_mode_with_minimal_fields(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="MINIMAL-001",
            title="Only Title",
        )

        submitted = PaperService.submit_paper(paper, strict=False)

        db_submitted = Paper.objects.get(pk=submitted.pk)
        assert submitted.state == db_submitted.state == PaperState.SUBMITTED
        assert submitted.submit_time == db_submitted.submit_time == approx_now()

    def test_non_strict_mode_requires_title(self, paper: Paper) -> None:
        update_object(paper, title="")

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper, strict=False)

        assert exc_info.value.errors == [{"title": "Title is required."}]

        paper.refresh_from_db()
        assert paper.state == PaperState.DRAFT
        assert paper.submit_time is None

    def test_raises_when_paper_is_withdrawn(self, user: User, paper: Paper) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be submitted",
        ):
            PaperService.submit_paper(paper)

        paper.refresh_from_db()
        assert paper.state == PaperState.DRAFT
        assert paper.submit_time is None

    def test_withdrawn_paper_reports_withdrawn_even_when_not_draft(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)
        update_object(
            paper,
            state=PaperState.SUBMITTED,
            submit_time=timezone.now(),
            withdraw_time=timezone.now(),
        )

        with pytest.raises(
            PaperWithdrawnError,
            match="Withdrawn papers cannot be submitted",
        ):
            PaperService.submit_paper(paper)

    @pytest.mark.parametrize(
        "state",
        [state for state in PaperState if state != PaperState.DRAFT],
    )
    def test_rejects_non_draft_state(
        self,
        user: User,
        paper: Paper,
        state: PaperState,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)
        update_object(paper, state=state)

        with pytest.raises(
            PaperStateError,
            match="Paper must be in Draft state to submit",
        ):
            PaperService.submit_paper(paper)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("title", "", "Title is required."),
            ("abstract", "", "Abstract is required."),
            ("contribution", "", "Contribution statement is required."),
        ],
    )
    def test_validates_field_required(
        self,
        user: User,
        paper: Paper,
        field: str,
        value: Any,
        message: str,
    ) -> None:
        update_object(paper, **{field: value})
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {field: message} in errors

    def test_validates_keywords_required(self, user: User, paper: Paper) -> None:
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"keywords": "At least two keywords are required."} in errors

    def test_validates_keywords_minimum_two(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=True)
        paper.keywords.add(Keyword.objects.create(text="Machine Learning"))

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"keywords": "At least two keywords are required."} in errors

    def test_validates_submission_file_required(self, paper: Paper) -> None:
        self.add_keywords(paper)
        self.add_author(paper, corresponding=True)

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"submissions": "A submission file is required."} in errors

    def test_validates_authors_required(self, user: User, paper: Paper) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"authors": "At least one author is required."} in errors

    def test_validates_corresponding_author_required(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, corresponding=False)

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"authors": "One author must be marked as corresponding."} in errors

    def test_validates_only_one_corresponding_author(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(
            paper,
            ordering=0,
            email="alice@example.com",
            corresponding=True,
        )
        self.add_author(
            paper,
            ordering=1,
            given_name="Bob",
            family_name="Jones",
            email="bob@example.com",
            corresponding=True,
        )

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert {"authors": "Only one author can be marked as corresponding."} in errors

    @pytest.mark.parametrize(
        ("field", "message"),
        [
            ("given_name", "given name"),
            ("family_name", "family name"),
            ("affiliation", "affiliation"),
            ("region_code", "region"),
            ("email", "email"),
        ],
    )
    def test_validates_author_field_required(
        self,
        user: User,
        paper: Paper,
        field: str,
        message: str,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(paper, **{field: ""}, corresponding=True)  # type: ignore[arg-type]

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert any("authors[1]" in error for error in errors)
        author_error = next(e for e in errors if "authors[1]" in e)
        assert message in author_error["authors[1]"]

    def test_validates_multiple_author_missing_fields(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        self.add_keywords(paper)
        self.add_submission(paper, user)
        self.add_author(
            paper,
            given_name="",
            family_name="",
            email="",
            corresponding=True,
        )

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        author_error = next(e for e in errors if "authors[1]" in e)
        message = author_error["authors[1]"]
        assert "given name" in message
        assert "family name" in message
        assert "email" in message

    def test_collects_all_validation_errors(self, paper: Paper) -> None:
        update_object(paper, title="", abstract="", contribution="")

        with pytest.raises(PaperSubmissionError) as exc_info:
            PaperService.submit_paper(paper)

        errors = exc_info.value.errors
        assert len(errors) >= 6
        assert {"title": "Title is required."} in errors
        assert {"abstract": "Abstract is required."} in errors
        assert {"contribution": "Contribution statement is required."} in errors
        assert {"keywords": "At least two keywords are required."} in errors
        assert {"submissions": "A submission file is required."} in errors
        assert {"authors": "At least one author is required."} in errors


@pytest.mark.django_db(transaction=True)
class TestSubmitPaperNotification:
    @pytest.fixture
    def owner(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    @pytest.fixture
    def paper(self, owner: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=owner,
            code="PAPER-001",
            title="Test Paper Title",
        )

    def test_sends_email_when_notify_is_true(
        self,
        owner: User,
        conference: Conference,
        track: Track,
        paper: Paper,
        mailoutbox: list[EmailMessage],
    ) -> None:
        PaperService.submit_paper(paper, strict=False, notify=True)

        [sent] = mailoutbox
        assert sent.to == [owner.email]
        assert conference.name in sent.subject
        assert paper.code in sent.body
        assert paper.title in sent.body
        assert track.display_name in sent.body

    def test_no_email_when_notify_is_false(
        self,
        paper: Paper,
        mailoutbox: list[EmailMessage],
    ) -> None:
        PaperService.submit_paper(paper, strict=False, notify=False)

        assert len(mailoutbox) == 0

    def test_no_email_by_default(
        self,
        paper: Paper,
        mailoutbox: list[EmailMessage],
    ) -> None:
        PaperService.submit_paper(paper, strict=False)

        assert len(mailoutbox) == 0

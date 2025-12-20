from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import Conference, Paper, PaperSubmission, Track
from app.conference.services.revision import RevisionService
from app.core.models import User
from app.utils.upload import FileTooLargeError, InvalidFileTypeError
from tests.helpers import any_str, update_object


@pytest.fixture(autouse=True)
def media_root(tmp_path: Path, settings: LazySettings) -> Path:
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.fixture
def sample_pdf(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.pdf").read_bytes()
    return SimpleUploadedFile("test.pdf", content, content_type="application/pdf")


@pytest.fixture
def revision_service_create_submission(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(RevisionService, "create_submission")


@pytest.mark.django_db(transaction=True)
class TestCreateMySubmission:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-my-submission",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
    ) -> None:
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["submission"] == {
            "uid": any_str,
            "display_name": "PAPER-001.pdf",
        }

        revision_service_create_submission.assert_called_once()
        call_kwargs = revision_service_create_submission.call_args.kwargs
        assert call_kwargs["paper"] == paper
        assert call_kwargs["uploader"] == user
        assert call_kwargs["file"].name == "test.pdf"

        assert PaperSubmission.objects.filter(paper=paper).count() == 1

    @pytest.mark.parametrize("state", [Paper.State.DRAFT, Paper.State.SUBMITTED])
    def test_allows_draft_and_submitted_states(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize(
        "state",
        [
            Paper.State.UNDER_REVIEW,
            Paper.State.REJECTED,
            Paper.State.ACCEPTED,
            Paper.State.ACCEPTED_REVISION_NEEDED,
        ],
    )
    def test_rejects_non_editable_states(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Draft or Submitted state" in response.json()["message"]

        revision_service_create_submission.assert_not_called()

    def test_rejects_withdrawn_paper(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Withdrawn" in response.json()["message"]

        revision_service_create_submission.assert_not_called()

    def test_file_too_large_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.services.revision.validate_upload",
            side_effect=FileTooLargeError("File size exceeds maximum allowed."),
        )
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "exceeds maximum" in response.json()["message"]

    def test_invalid_file_type_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.services.revision.validate_upload",
            side_effect=InvalidFileTypeError("File type not allowed."),
        )
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "not allowed" in response.json()["message"]

    def test_paper_not_found(
        self,
        client: Client,
        user: User,
        conference: Conference,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(user)

        response = client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_accessible(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        client: Client,
        user: User,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(user)

        response = client.post(
            self.path("nonexistent-conference", paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

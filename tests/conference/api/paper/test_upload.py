from http import HTTPStatus
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    PaperState,
    PaperSubmission,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService, RevisionService
from app.core.models import User
from app.utils.files import FileTooLargeError, InvalidFileTypeError
from tests.helpers import any_str, update_object


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

    @pytest.mark.parametrize("state", [PaperState.DRAFT, PaperState.SUBMITTED])
    def test_allows_draft_and_submitted_states(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        state: PaperState,
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
            PaperState.UNDER_REVIEW,
            PaperState.REJECTED,
            PaperState.ACCEPTED,
            PaperState.ACCEPTED_REVISION_NEEDED,
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
        state: PaperState,
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

    def test_conference_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_track_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(track, active=False)
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


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.mark.django_db(transaction=True)
class TestCreateSubmission:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-submission",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        settings: LazySettings,
        conference: Conference,
        conference_chair: User,
        user: User,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["owner"]["uid"] == str(user.uid)
        assert data["submission"] == {
            "uid": any_str,
            "display_name": "PAPER-001.pdf",
        }

        revision_service_create_submission.assert_called_once()
        call_kwargs = revision_service_create_submission.call_args.kwargs
        assert call_kwargs["paper"] == paper
        assert call_kwargs["uploader"] == conference_chair
        assert call_kwargs["skip_cleanup"] is True
        assert call_kwargs["max_size"] == settings.MAX_SUBMISSION_SIZE * 4
        assert call_kwargs["file"].name == "test.pdf"

        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)

        assert PaperSubmission.objects.filter(paper=paper).count() == 1

    @pytest.mark.parametrize(
        "state",
        [PaperState.DRAFT, PaperState.SUBMITTED, PaperState.UNDER_REVIEW],
    )
    def test_allows_non_decided_states(
        self,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        state: PaperState,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(track_admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize("state", PaperState.decided())
    def test_track_admin_cannot_upload_to_decided_paper(
        self,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        state: PaperState,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(track_admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "conference admins" in response.json()["message"]

        revision_service_create_submission.assert_not_called()

    @pytest.mark.parametrize("state", PaperState.decided())
    def test_global_admin_can_upload_to_decided_paper(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
        global_admin: User,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(global_admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize("state", PaperState.decided())
    def test_conference_admin_can_upload_to_decided_paper(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    def test_rejects_withdrawn_paper(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Withdrawn" in response.json()["message"]

        revision_service_create_submission.assert_not_called()

    def test_invalid_file_type_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mocker.patch(
            "app.conference.services.revision.validate_upload",
            side_effect=InvalidFileTypeError("File type not allowed."),
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "not allowed" in response.json()["message"]

    def test_paper_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.none()
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        client: Client,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path("nonexistent-conference", "PAPER-001"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(conference_chair)

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

    def test_authorization_user_without_roles(
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
        assert response.status_code == HTTPStatus.FORBIDDEN

        revision_service_create_submission.assert_not_called()

    def test_authorization_global_admin(
        self,
        client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(global_admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        revision_service_create_submission: MagicMock,
        mock_visible_papers: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(admin)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        revision_service_create_submission.assert_called_once()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_authorization_track_non_admin_forbidden(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

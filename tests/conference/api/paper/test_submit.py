from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
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
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError, PaperSubmissionError
from app.core.models import User
from tests.helpers import update_object


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
def paper_service_submit(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "submit_paper")


@pytest.fixture
def paper_service_unsubmit(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "unsubmit_paper")


@pytest.mark.django_db
class TestSubmitMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:submit-my-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_submit: MagicMock,
    ) -> None:
        def submit_side_effect(p: Paper, *_: Any, **__: Any) -> Paper:
            p.state = Paper.State.SUBMITTED
            p.save(update_fields=["state"])
            return p

        paper_service_submit.side_effect = submit_side_effect
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["state"] == "Submitted"

        paper_service_submit.assert_called_once()
        call_kwargs = paper_service_submit.call_args.kwargs
        assert call_kwargs["strict"] is True

    def test_handle_paper_state_error(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_submit: MagicMock,
    ) -> None:
        paper_service_submit.side_effect = PaperStateError("Paper state error.")
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Paper state error." in response.json()["message"]

    def test_test_handle_paper_validation_errors(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_submit: MagicMock,
    ) -> None:
        errors = [
            {"title": "Title is required."},
            {"abstract": "Abstract is required."},
            {"contribution": "Contribution statement is required."},
            {"keywords": "At least one keyword is required."},
            {"submissions": "A submission file is required."},
            {"authors": "At least one author is required."},
        ]
        paper_service_submit.side_effect = PaperSubmissionError(errors)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json() == {
            "message": "Paper submission validation failed.",
            "details": [
                {"title": "Title is required."},
                {"abstract": "Abstract is required."},
                {"contribution": "Contribution statement is required."},
                {"keywords": "At least one keyword is required."},
                {"submissions": "A submission file is required."},
                {"authors": "At least one author is required."},
            ],
        }

    def test_paper_not_found(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_accessible(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        client: Client,
        user: User,
        paper: Paper,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path("nonexistent-conference", paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_track_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        update_object(track, active=False)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUnsubmitMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:unsubmit-my-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_unsubmit: MagicMock,
    ) -> None:
        update_object(paper, state=Paper.State.SUBMITTED, submit_time=timezone.now())

        def unsubmit_side_effect(p: Paper) -> Paper:
            p.state = Paper.State.DRAFT
            p.submit_time = None
            p.save(update_fields=["state", "submit_time"])
            return p

        paper_service_unsubmit.side_effect = unsubmit_side_effect
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["state"] == "Draft"

        paper_service_unsubmit.assert_called_once_with(paper)

    def test_handle_paper_state_error(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_unsubmit: MagicMock,
    ) -> None:
        paper_service_unsubmit.side_effect = PaperStateError(
            "Paper must be in Submitted state to unsubmit."
        )
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert (
            "Paper must be in Submitted state to unsubmit."
            in response.json()["message"]
        )

    def test_paper_not_found(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_accessible(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        client: Client,
        user: User,
        paper: Paper,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path("nonexistent-conference", paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_track_inactive(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        update_object(track, active=False)
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.mark.django_db
class TestSubmitPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:submit-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        paper: Paper,
        paper_service_submit: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        def submit_side_effect(p: Paper, *_: Any, **__: Any) -> Paper:
            p.state = Paper.State.SUBMITTED
            p.save(update_fields=["state"])
            return p

        paper_service_submit.side_effect = submit_side_effect
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["state"] == "Submitted"
        assert data["owner"]["uid"] == str(user.uid)

        paper_service_submit.assert_called_once()
        call_kwargs = paper_service_submit.call_args.kwargs
        assert call_kwargs["strict"] is False

        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)

    def test_handle_paper_state_error(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        paper_service_submit: MagicMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        paper_service_submit.side_effect = PaperStateError("Paper state error.")
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Paper state error." in response.json()["message"]

    def test_test_handle_paper_validation_errors(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        paper_service_submit: MagicMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        errors = [{"title": "Title is required."}]
        paper_service_submit.side_effect = PaperSubmissionError(errors)
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json() == {
            "message": "Paper submission validation failed.",
            "details": [{"title": "Title is required."}],
        }

    def test_paper_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.none()
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        client: Client,
        conference_chair: User,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_submit: MagicMock,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_submit.assert_not_called()

    def test_authorization_global_admin(
        self,
        client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        paper_service_submit: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_service_submit.return_value = paper
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(global_admin)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        paper_service_submit.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        paper: Paper,
        paper_service_submit: MagicMock,
        mock_visible_papers: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        paper_service_submit.return_value = paper
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(admin)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        paper_service_submit.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        paper_service_submit: MagicMock,
        mock_visible_papers: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        paper_service_submit.return_value = paper
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        client.force_login(admin)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        paper_service_submit.assert_called_once()

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
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
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
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

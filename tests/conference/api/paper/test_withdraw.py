from http import HTTPStatus
from unittest.mock import MagicMock

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
from app.conference.services.paper import PaperWithdrawnError
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
def paper_service_withdraw(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "withdraw_paper")


@pytest.mark.django_db
class TestWithdrawMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:withdraw-my-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        def withdraw_side_effect(p: Paper) -> Paper:
            p.withdraw_time = timezone.now()
            p.save(update_fields=["withdraw_time"])
            return p

        paper_service_withdraw.side_effect = withdraw_side_effect
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["state"] == "Withdrawn"

        paper_service_withdraw.assert_called_once_with(paper)

    def test_handle_already_withdrawn_error(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        paper_service_withdraw.side_effect = PaperWithdrawnError(
            "Paper has already been withdrawn."
        )
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Paper has already been withdrawn." in response.json()["message"]

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
class TestWithdrawPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:withdraw-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        def withdraw_side_effect(p: Paper) -> Paper:
            p.withdraw_time = timezone.now()
            p.save(update_fields=["withdraw_time"])
            return p

        paper_service_withdraw.side_effect = withdraw_side_effect
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["visible_state"] == "Withdrawn"
        assert data["owner"]["uid"] == str(user.uid)

        paper_service_withdraw.assert_called_once_with(paper)

    def test_handle_already_withdrawn_error(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        paper_service_withdraw.side_effect = PaperWithdrawnError(
            "Paper has already been withdrawn."
        )
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Paper has already been withdrawn." in response.json()["message"]

    def test_paper_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
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
        paper_service_withdraw: MagicMock,
    ) -> None:
        client.force_login(user)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_withdraw.assert_not_called()

    def test_authorization_global_admin(
        self,
        client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        paper_service_withdraw.return_value = paper
        client.force_login(global_admin)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        paper_service_withdraw.assert_called_once()

    def test_authorization_conference_chair(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        paper_service_withdraw.return_value = paper
        client.force_login(conference_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        paper_service_withdraw.assert_called_once()

    def test_authorization_conference_secretary_forbidden(
        self,
        client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
        paper_service_withdraw: MagicMock,
    ) -> None:
        client.force_login(conference_secretary)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_withdraw.assert_not_called()

    @pytest.mark.parametrize("track_role", list(TrackRole))
    def test_authorization_track_roles_forbidden(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        paper_service_withdraw: MagicMock,
        track_role: TrackRole,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=track_role,
        )
        client.force_login(track_admin)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_withdraw.assert_not_called()

    @pytest.mark.parametrize(
        "non_chair_role",
        [role for role in ConferenceRole if role != ConferenceRole.CHAIR],
    )
    def test_authorization_conference_non_chair_forbidden(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        paper: Paper,
        paper_service_withdraw: MagicMock,
        non_chair_role: ConferenceRole,
    ) -> None:
        non_chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_chair,
            role=non_chair_role,
        )
        client.force_login(non_chair)

        response = client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_withdraw.assert_not_called()

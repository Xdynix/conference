from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

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
def target_track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def paper_service_relocate(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "relocate_paper")


@pytest.mark.django_db
class TestRelocatePaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:relocate-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["track"]["uid"] == str(target_track.uid)

        paper_service_relocate.assert_called_once_with(paper, target_track)

    def test_track_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_relocate: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(ULID())},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "target_track"]
        assert error["msg"] == "Track not found."

        paper_service_relocate.assert_not_called()

    def test_track_inactive_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        update_object(target_track, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["msg"] == "Track not found."

        paper_service_relocate.assert_not_called()

    def test_same_track_bad_request(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(track.uid)},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        data = response.json()
        assert "different from current track" in data["message"]

        paper_service_relocate.assert_called_once()

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        target_track: Track,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        target_track: Track,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        target_track: Track,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent-conference", "PAPER-001"),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        target_track: Track,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        target_track: Track,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_relocate.assert_not_called()

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        paper_service_relocate.return_value = paper
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_relocate.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        paper_service_relocate.return_value = paper
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_relocate.assert_called_once()

    def test_authorization_conference_secretary_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_relocate.assert_not_called()

    @pytest.mark.parametrize("track_role", list(TrackRole))
    def test_authorization_track_roles_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
        track_role: TrackRole,
    ) -> None:
        track_user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_user,
            role=track_role,
        )
        api_client.force_login(track_user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_relocate.assert_not_called()

    @pytest.mark.parametrize(
        "non_chair_role",
        [role for role in ConferenceRole if role != ConferenceRole.CHAIR],
    )
    def test_authorization_conference_non_chair_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        target_track: Track,
        paper_service_relocate: MagicMock,
        non_chair_role: ConferenceRole,
    ) -> None:
        non_chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_chair,
            role=non_chair_role,
        )
        api_client.force_login(non_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"target_track": str(target_track.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_relocate.assert_not_called()

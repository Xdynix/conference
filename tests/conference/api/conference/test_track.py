from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Conference, Track
from app.conference.services import TrackService
from app.core.models import User
from tests.helpers import any_str


@pytest.mark.django_db
class TestCreateTrack:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-track", args=[conference_name])

    @pytest.fixture
    def track_service_create(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(TrackService, "create_track")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track_service_create: MagicMock,
    ) -> None:
        existing_track = Track.objects.create(
            conference=conference,
            display_name="Research Track",
            ordering=5,
            visibility=Track.Visibility.PUBLIC,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Operations Track",
                "visibility": Track.Visibility.ADMIN_ONLY,
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(existing_track.uid),
                    "display_name": existing_track.display_name,
                    "visibility": existing_track.visibility,
                    "submissions_enabled": False,
                },
                {
                    "uid": any_str,
                    "display_name": "Operations Track",
                    "visibility": Track.Visibility.ADMIN_ONLY,
                    "submissions_enabled": False,
                },
            ],
        }

        track_service_create.assert_called_once_with(
            conference_name=conference.name,
            display_name="Operations Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )

    def test_conference_chair_can_create_track(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track_service_create: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Chair Created",
                "visibility": Track.Visibility.PUBLIC,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        track_service_create.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        track_service_create: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Unauthorized Track"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        track_service_create.assert_not_called()

    def test_handle_does_not_exist(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track_service_create: MagicMock,
    ) -> None:
        track_service_create.side_effect = Conference.DoesNotExist
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Chair Created",
                "visibility": Track.Visibility.PUBLIC,
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestUpdateTrack:
    @classmethod
    def path(cls, conference_name: str, track_uid: ULID) -> str:
        return reverse("api-1.0.0:update-track", args=[conference_name, track_uid])

    @pytest.fixture
    def track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Infrastructure",
            visibility=Track.Visibility.PUBLIC,
        )

    @pytest.fixture
    def track_service_update(self, mocker: MockerFixture) -> AsyncMock:
        return mocker.spy(TrackService, "update_track")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(track.conference.name, track.uid),
            data={
                "display_name": "Infrastructure & Ops",
                "visibility": Track.Visibility.ADMIN_ONLY,
                "submissions_enabled": True,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": track.conference.name,
            "display_name": track.conference.display_name,
            "visibility": track.conference.visibility,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": "Infrastructure & Ops",
                    "visibility": Track.Visibility.ADMIN_ONLY,
                    "submissions_enabled": True,
                },
            ],
        }

        track_service_update.assert_awaited_once_with(
            conference_name=track.conference.name,
            track_uid=track.uid,
            display_name="Infrastructure & Ops",
            visibility=Track.Visibility.ADMIN_ONLY,
            submissions_enabled=True,
        )

    def test_empty_payload(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(track.conference.name, track.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        track_service_update.assert_awaited_once_with(
            conference_name=track.conference.name,
            track_uid=track.uid,
        )

    def test_conference_chair_can_update_track(
        self,
        api_client: Client,
        conference_chair: User,
        track: Track,
        track_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(track.conference.name, track.uid),
            data={"display_name": "Chair Update"},
        )
        assert response.status_code == HTTPStatus.OK

        track_service_update.assert_awaited_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_secretary: User,
        track: Track,
        track_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.patch(
            self.path(track.conference.name, track.uid),
            data={"display_name": "Unauthorized Update"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        track_service_update.assert_not_called()

    def test_handle_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_update: AsyncMock,
    ) -> None:
        track_service_update.side_effect = Track.DoesNotExist
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(track.conference.name, track.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestDeleteTrack:
    @classmethod
    def path(cls, conference_name: str, track_uid: ULID) -> str:
        return reverse("api-1.0.0:delete-track", args=[conference_name, track_uid])

    @pytest.fixture
    def track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Analytics",
            ordering=1,
            visibility=Track.Visibility.PUBLIC,
        )

    @pytest.fixture
    def remaining_track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Governance",
            ordering=2,
            visibility=Track.Visibility.ADMIN_ONLY,
        )

    @pytest.fixture
    def track_service_deactivate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(TrackService, "deactivate_track")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        remaining_track: Track,
        track_service_deactivate: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(track.conference.name, track.uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": track.conference.name,
            "display_name": track.conference.display_name,
            "visibility": track.conference.visibility,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(remaining_track.uid),
                    "display_name": remaining_track.display_name,
                    "visibility": remaining_track.visibility,
                    "submissions_enabled": False,
                },
            ],
        }

        track_service_deactivate.assert_called_once_with(
            conference_name=track.conference.name,
            track_uid=track.uid,
        )

    def test_conference_chair_can_delete_track(
        self,
        api_client: Client,
        conference_chair: User,
        track: Track,
        track_service_deactivate: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(track.conference.name, track.uid))
        assert response.status_code == HTTPStatus.OK

        track_service_deactivate.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_secretary: User,
        track: Track,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.delete(self.path(track.conference.name, track.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_handle_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_deactivate: AsyncMock,
    ) -> None:
        track_service_deactivate.side_effect = Track.DoesNotExist
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(track.conference.name, track.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestMoveTrack:
    @classmethod
    def path(cls, conference_name: str, track_uid: str | ULID) -> str:
        return reverse("api-1.0.0:move-track", args=[conference_name, track_uid])

    @pytest.fixture
    def track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Track",
        )

    @pytest.fixture
    def track_service_move(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(TrackService, "move_track")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track_service_move: MagicMock,
    ) -> None:
        first = Track.objects.create(
            conference=conference,
            display_name="First Track",
            ordering=1,
            visibility=Track.Visibility.PUBLIC,
        )
        second = Track.objects.create(
            conference=conference,
            display_name="Second Track",
            ordering=2,
            visibility=Track.Visibility.PUBLIC,
        )
        third = Track.objects.create(
            conference=conference,
            display_name="Third Track",
            ordering=3,
            visibility=Track.Visibility.PUBLIC,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, third.uid),
            data={"after_track": str(first.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        assert [track["uid"] for track in response.json()["tracks"]] == [
            str(first.uid),
            str(third.uid),
            str(second.uid),
        ]

        track_service_move.assert_called_once_with(
            conference_name=conference.name,
            track_uid=third.uid,
            after_track_uid=str(first.uid),
        )

    def test_conference_chair_can_move_track(
        self,
        api_client: Client,
        conference_chair: User,
        track: Track,
        track_service_move: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(track.conference.name, track.uid),
            data={"after_track": None},
        )
        assert response.status_code == HTTPStatus.OK

        track_service_move.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_secretary: User,
        track: Track,
        track_service_move: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(track.conference.name, track.uid),
            data={"after_track": None},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        track_service_move.assert_not_called()

    @pytest.mark.parametrize(
        "exc",
        [Conference.DoesNotExist, Track.DoesNotExist],
        ids=["ConferenceDoesNotExist", "TrackDoesNotExist"],
    )
    def test_handle_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_move: MagicMock,
        exc: type[Exception],
    ) -> None:
        track_service_move.side_effect = exc
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(track.conference.name, track.uid),
            data={"after_track": None},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_handle_value_error(
        self,
        api_client: Client,
        global_admin: User,
        track: Track,
        track_service_move: MagicMock,
    ) -> None:
        track_service_move.side_effect = ValueError("Invalid target.")
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(track.conference.name, track.uid),
            data={"after_track": None},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "after_track"]
        assert "Invalid target." in error["msg"]

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Conference, Track, TrackVisibility
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
            visibility=TrackVisibility.PUBLIC,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Operations Track",
                "visibility": TrackVisibility.ADMIN_ONLY,
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "registration_enabled": False,
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
                    "visibility": TrackVisibility.ADMIN_ONLY,
                    "submissions_enabled": False,
                },
            ],
        }

        track_service_create.assert_called_once_with(
            conference_name=conference.name,
            display_name="Operations Track",
            visibility=TrackVisibility.ADMIN_ONLY,
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
                "visibility": TrackVisibility.PUBLIC,
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
                "visibility": TrackVisibility.PUBLIC,
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
            visibility=TrackVisibility.PUBLIC,
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
                "visibility": TrackVisibility.ADMIN_ONLY,
                "submissions_enabled": True,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": track.conference.name,
            "display_name": track.conference.display_name,
            "visibility": track.conference.visibility,
            "registration_enabled": False,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": "Infrastructure & Ops",
                    "visibility": TrackVisibility.ADMIN_ONLY,
                    "submissions_enabled": True,
                },
            ],
        }

        track_service_update.assert_awaited_once_with(
            conference_name=track.conference.name,
            track_uid=track.uid,
            display_name="Infrastructure & Ops",
            visibility=TrackVisibility.ADMIN_ONLY,
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
            visibility=TrackVisibility.PUBLIC,
        )

    @pytest.fixture
    def remaining_track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Governance",
            ordering=2,
            visibility=TrackVisibility.ADMIN_ONLY,
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
            "registration_enabled": False,
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
class TestReorderTracks:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:reorder-tracks", args=[conference_name])

    @pytest.fixture
    def tracks(self, conference: Conference) -> tuple[Track, Track, Track]:
        return (
            Track.objects.create(
                conference=conference,
                display_name="First Track",
                ordering=0,
                visibility=TrackVisibility.PUBLIC,
            ),
            Track.objects.create(
                conference=conference,
                display_name="Second Track",
                ordering=1,
                visibility=TrackVisibility.PUBLIC,
            ),
            Track.objects.create(
                conference=conference,
                display_name="Third Track",
                ordering=2,
                visibility=TrackVisibility.ADMIN_ONLY,
            ),
        )

    @pytest.fixture
    def track_service_reorder(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(TrackService, "reorder_tracks")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, Track, Track],
        track_service_reorder: MagicMock,
    ) -> None:
        first, second, third = tracks
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data=[str(third.uid), str(first.uid), str(second.uid)],
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "registration_enabled": False,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(third.uid),
                    "display_name": third.display_name,
                    "visibility": third.visibility,
                    "submissions_enabled": False,
                },
                {
                    "uid": str(first.uid),
                    "display_name": first.display_name,
                    "visibility": first.visibility,
                    "submissions_enabled": False,
                },
                {
                    "uid": str(second.uid),
                    "display_name": second.display_name,
                    "visibility": second.visibility,
                    "submissions_enabled": False,
                },
            ],
        }

        track_service_reorder.assert_called_once_with(
            conference_name=conference.name,
            track_uids=[third.uid, first.uid, second.uid],
        )

    def test_conference_chair_can_reorder(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        tracks: tuple[Track, Track, Track],
        track_service_reorder: MagicMock,
    ) -> None:
        first, second, third = tracks
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=[str(first.uid), str(second.uid), str(third.uid)],
        )
        assert response.status_code == HTTPStatus.OK

        track_service_reorder.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_secretary: User,
        conference: Conference,
        tracks: tuple[Track, Track, Track],
        track_service_reorder: MagicMock,
    ) -> None:
        first, second, third = tracks
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name),
            data=[str(first.uid), str(second.uid), str(third.uid)],
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        track_service_reorder.assert_not_called()

    def test_handle_conference_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, Track, Track],
        track_service_reorder: MagicMock,
    ) -> None:
        first, second, third = tracks
        track_service_reorder.side_effect = Conference.DoesNotExist
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data=[str(first.uid), str(second.uid), str(third.uid)],
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_handle_value_error(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, Track, Track],
        track_service_reorder: MagicMock,
    ) -> None:
        first, second, _ = tracks
        track_service_reorder.side_effect = ValueError("Missing UIDs: 01ABC.")
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data=[str(first.uid), str(second.uid)],
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "Missing UIDs" in response.json()["message"]

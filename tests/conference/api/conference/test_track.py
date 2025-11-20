from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def conference_chair(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.mark.django_db
class TestCreateTrack:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-track", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
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
                },
                {
                    "uid": any_str,
                    "display_name": "Operations Track",
                    "visibility": Track.Visibility.ADMIN_ONLY,
                },
            ],
        }

        first, second = conference.tracks.all()
        assert first.display_name == "Research Track"
        assert second.display_name == "Operations Track"
        assert first.ordering < second.ordering

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Unauthorized Track"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_inactive_conference_returns_404(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Dormant Track"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_chair_can_create_track(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
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
        assert Track.objects.filter(
            conference=conference,
            display_name="Chair Created",
        ).exists()


@pytest.mark.django_db
class TestUpdateTrack:
    @classmethod
    def path(cls, conference_name: str, track_id: ULID) -> str:
        return reverse("api-1.0.0:update-track", args=[conference_name, track_id])

    @pytest.fixture
    def track(self, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name="Infrastructure",
            visibility=Track.Visibility.PUBLIC,
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, track.uid),
            data={
                "display_name": "Infrastructure & Ops",
                "visibility": Track.Visibility.ADMIN_ONLY,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": "Infrastructure & Ops",
                    "visibility": Track.Visibility.ADMIN_ONLY,
                },
            ],
        }

        track.refresh_from_db()
        assert track.display_name == "Infrastructure & Ops"
        assert track.visibility == Track.Visibility.ADMIN_ONLY

    def test_empty_payload_returns_existing_state(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, track.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["tracks"] == [
            {
                "uid": str(track.uid),
                "display_name": track.display_name,
                "visibility": track.visibility,
            },
        ]

        track.refresh_from_db()
        assert track.display_name == "Infrastructure"
        assert track.visibility == Track.Visibility.PUBLIC

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, track.uid),
            data={"display_name": "Unauthorized Update"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_chair_can_update_track(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, track.uid),
            data={"display_name": "Chair Update"},
        )
        assert response.status_code == HTTPStatus.OK

        track.refresh_from_db()
        assert track.display_name == "Chair Update"


@pytest.mark.django_db
class TestDeleteTrack:
    @classmethod
    def path(cls, conference_name: str, track_id: ULID) -> str:
        return reverse("api-1.0.0:delete-track", args=[conference_name, track_id])

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

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        remaining_track: Track,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, track.uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "keywords": [],
            "tracks": [
                {
                    "uid": str(remaining_track.uid),
                    "display_name": remaining_track.display_name,
                    "visibility": remaining_track.visibility,
                },
            ],
        }

        track.refresh_from_db()
        assert track.active is False

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, track.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_chair_can_delete_track(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(conference.name, track.uid))
        assert response.status_code == HTTPStatus.OK

        track.refresh_from_db()
        assert track.active is False


@pytest.mark.django_db
class TestMoveTrack:
    @classmethod
    def path(cls, conference_name: str, track_id: str | ULID) -> str:
        return reverse("api-1.0.0:move-track", args=[conference_name, track_id])

    @pytest.fixture
    def tracks(self, conference: Conference) -> tuple[Track, ...]:
        return tuple(
            Track.objects.create(
                conference=conference,
                display_name=name,
                ordering=idx,
                visibility=Track.Visibility.PUBLIC,
            )
            for idx, name in enumerate(["Alpha", "Beta", "Gamma"])
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
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

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        assert first.ordering < third.ordering < second.ordering

    def test_empty_after_track_moves_track_to_top(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, third.uid), data={})
        assert response.status_code == HTTPStatus.OK
        assert [track["uid"] for track in response.json()["tracks"]] == [
            str(third.uid),
            str(first.uid),
            str(second.uid),
        ]

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        assert third.ordering == 0
        assert third.ordering < first.ordering < second.ordering

    def test_cannot_move_track_after_itself(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, *_ = tracks
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, first.uid),
            data={"after_track": str(first.uid)},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {
            "message": "Track cannot be moved after itself.",
        }

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, _ = tracks
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, first.uid),
            data={"after_track": str(second.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_nonexistent_after_track_returns_error(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, _ = tracks
        missing_track_uid = ULID()
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, first.uid),
            data={"after_track": str(missing_track_uid)},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {"message": "Target track does not exist."}

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.ordering < second.ordering

    def test_conference_chair_can_move_track(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, third.uid),
            data={"after_track": str(first.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        assert first.ordering < third.ordering < second.ordering

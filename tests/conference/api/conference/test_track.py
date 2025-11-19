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
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.mark.django_db
class TestCreateTrack:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-track", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        existing_track = Track.objects.create(
            conference=conference,
            display_name="Research Track",
            ordering=5,
            visibility=Track.Visibility.PUBLIC,
        )
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(user)

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

        tracks = list(conference.tracks.all())
        assert [track.display_name for track in tracks] == [
            "Research Track",
            "Operations Track",
        ]
        assert tracks[-1].ordering == existing_track.ordering + 1

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
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
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Dormant Track"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


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
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(user)

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
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(user)

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
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
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

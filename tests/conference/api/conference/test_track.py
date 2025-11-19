from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.mark.django_db
class TestCreateTrack:
    @staticmethod
    def path(conference_name: str) -> str:
        return reverse(
            "api-1.0.0:create-track",
            kwargs={"conference_name": conference_name},
        )

    @pytest.fixture
    def conference(self) -> Conference:
        return Conference.objects.create(
            name="tech-conf",
            display_name="Tech Conference",
        )

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    def test_global_admin_creates_track(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
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

    def test_conference_chair_can_create_track(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Blue Team Track",
                "visibility": Track.Visibility.PUBLIC,
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert [track["display_name"] for track in response.json()["tracks"]] == [
            "Blue Team Track",
        ]

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Unauthorized Track"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_inactive_conference_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
    ) -> None:
        update_object(conference, active=False)
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Dormant Track"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

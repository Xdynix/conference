from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import Conference, Keyword, KeywordSet, Track
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str


@pytest.mark.django_db
class TestCreateConference:
    path = reverse("api-1.0.0:create-conference")

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    def test_happy_path(self, api_client: Client, authorized_user: User) -> None:
        keyword = Keyword.objects.create(text="AI")
        keyword_set = KeywordSet.objects.create(name="security")
        keyword_from_set = Keyword.objects.create(text="Analysis")
        keyword_set.keywords.set([keyword_from_set])
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "name": "sec-conf",
                "display_name": "Security Conf",
                "visibility": Conference.Visibility.PUBLIC,
                "keywords": [keyword.text],
                "keyword_sets": [keyword_set.name],
                "tracks": [
                    {
                        "display_name": "Research Track",
                        "visibility": Track.Visibility.PUBLIC,
                    },
                    {
                        "display_name": "Operations Track",
                        "visibility": Track.Visibility.ADMIN_ONLY,
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data == {
            "name": "sec-conf",
            "display_name": "Security Conf",
            "keywords": ["AI", "Analysis"],
            "visibility": Conference.Visibility.PUBLIC,
            "tracks": [
                {
                    "uid": any_str,
                    "display_name": "Research Track",
                    "visibility": Track.Visibility.PUBLIC,
                },
                {
                    "uid": any_str,
                    "display_name": "Operations Track",
                    "visibility": Track.Visibility.ADMIN_ONLY,
                },
            ],
        }

        conference = Conference.objects.get(name="sec-conf")
        assert conference.display_name == "Security Conf"
        assert conference.visibility == Conference.Visibility.PUBLIC
        assert list(conference.keywords.values_list("text", flat=True)) == [
            "AI",
            "Analysis",
        ]
        assert conference.tracks.count() == 2
        first_track, second_track = conference.tracks.all()
        assert str(first_track.uid) == data["tracks"][0]["uid"]
        assert first_track.display_name == "Research Track"
        assert first_track.visibility == Track.Visibility.PUBLIC
        assert str(second_track.uid) == data["tracks"][1]["uid"]
        assert second_track.display_name == "Operations Track"
        assert second_track.visibility == Track.Visibility.ADMIN_ONLY

    def test_minimal_payload_uses_defaults(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "name": "minimal-conf",
                "display_name": "Minimal Conf",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {
            "name": "minimal-conf",
            "display_name": "Minimal Conf",
            "visibility": Conference.Visibility.ADMIN_ONLY,
            "keywords": [],
            "tracks": [],
        }

    def test_duplicate_name_conflict(
        self, api_client: Client, authorized_user: User
    ) -> None:
        Conference.objects.create(
            name="dup-conf",
            display_name="Existing Conf",
        )
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "name": "dup-conf",
                "display_name": "New Conf",
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "already exists" in response.json()["message"]

    def test_unknown_keyword_returns_422(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "name": "unknown-keyword-conf",
                "display_name": "Unknown Keyword Conf",
                "keywords": ["nonexistent"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json()["message"].startswith("Unknown keywords")

    def test_unknown_keyword_set_returns_422(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "name": "unknown-keyword-set-conf",
                "display_name": "Unknown Keyword Set Conf",
                "keyword_sets": ["missing-set"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json()["message"].startswith("Unknown keyword sets")

    def test_unauthorized_user_forbidden(self, api_client: Client) -> None:
        user = User.objects.create_user(username="regular")
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={
                "name": "regular-conf",
                "display_name": "Regular Conf",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

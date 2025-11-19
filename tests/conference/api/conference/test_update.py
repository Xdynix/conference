from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    KeywordSet,
    Track,
)
from app.core.models import User
from tests.helpers import any_list, update_object


@pytest.mark.django_db
class TestUpdateConference:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:update-conference", args=[conference_name])

    @pytest.fixture
    def conference(self) -> Conference:
        conference = Conference.objects.create(
            name="cyber-2025",
            display_name="Cyber Security Conference",
        )
        Track.objects.create(
            conference=conference,
            display_name="Research Track",
            visibility=Track.Visibility.PUBLIC,
            ordering=1,
        )
        Track.objects.create(
            conference=conference,
            display_name="Operations Track",
            visibility=Track.Visibility.ADMIN_ONLY,
            ordering=2,
        )
        return conference

    @pytest.fixture
    def authorized_user(self, faker: Faker, conference: Conference) -> User:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        return user

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        authorized_user: User,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        keyword_from_set = Keyword.objects.create(text="Security")
        keyword_set = KeywordSet.objects.create(name="sec-suite")
        keyword_set.keywords.set([keyword_from_set])
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "display_name": "Cyber Security Summit",
                "visibility": Conference.Visibility.PUBLIC,
                "keywords": [keyword.text],
                "keyword_sets": [keyword_set.name],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == {
            "name": "cyber-2025",
            "display_name": "Cyber Security Summit",
            "visibility": Conference.Visibility.PUBLIC,
            "keywords": ["AI", "Security"],
            "tracks": any_list,
        }

        conference.refresh_from_db()
        assert conference.display_name == "Cyber Security Summit"
        assert conference.visibility == Conference.Visibility.PUBLIC
        assert list(conference.keywords.values_list("text", flat=True)) == [
            "AI",
            "Security",
        ]

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.PUBLIC)
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={"display_name": "Unauthorized Update"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unknown_keyword_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(conference.name),
            data={"keywords": ["nonexistent"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json()["message"].startswith("Unknown keywords")

        conference.refresh_from_db()
        assert list(conference.keywords.values_list("text", flat=True)) == []

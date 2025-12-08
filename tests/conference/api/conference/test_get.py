from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import Conference, Keyword, Track
from app.conference.services import ConferenceService
from app.core.models import User


@pytest.mark.django_db
class TestGetConference:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:get-conference", args=[conference_name])

    def test_happy_path(self, mocker: MockerFixture, api_client: Client) -> None:
        conference = Conference.objects.create(
            name="conf",
            display_name="Conf",
            visibility=Conference.Visibility.PUBLIC,
        )
        keywords = [
            Keyword.objects.create(text="ai"),
            Keyword.objects.create(text="security"),
            Keyword.objects.create(text="cloud"),
        ]
        conference.keywords.set(keywords)
        track = Track.objects.create(
            conference=conference,
            display_name="Main Track",
            visibility=Track.Visibility.PUBLIC,
        )
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        user = User.objects.create_user(username="reader")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "keywords": ["ai", "cloud", "security"],
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": track.display_name,
                    "visibility": track.visibility,
                },
            ],
        }

        mock_visible.assert_awaited_once_with(user)

    def test_returns_404_when_conference_not_visible(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.none(),
        )

        response = api_client.get(self.path("missing"))

        assert response.status_code == HTTPStatus.NOT_FOUND

        mock_visible.assert_awaited_once_with(AnonymousUser())

from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceVisibility,
    IEEEeCopyrightConfig,
    Keyword,
    Track,
    TrackVisibility,
)
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
            visibility=ConferenceVisibility.PUBLIC,
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
            visibility=TrackVisibility.PUBLIC,
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
            "registration_enabled": False,
            "location": "",
            "paper_submission_instructions": "",
            "paper_submission_instructions_html": "",
            "paper_final_instructions": "",
            "paper_final_instructions_html": "",
            "keywords": ["ai", "cloud", "security"],
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": track.display_name,
                    "visibility": track.visibility,
                    "submissions_enabled": False,
                    "accepts_submissions": False,
                    "ieee_ecopyright_required": False,
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

    def test_includes_ieee_ecopyright_config(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        conference = Conference.objects.create(
            name="conf",
            display_name="Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Proceedings of ICSE 2025",
            article_source="ICSE25",
        )
        mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        user = User.objects.create_user(username="reader")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["ieee_ecopyright_config"] == {
            "publication_title": config.publication_title,
            "article_source": config.article_source,
        }

    def test_track_ieee_ecopyright_required_when_config_exists(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        conference = Conference.objects.create(
            name="conf",
            display_name="Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        Track.objects.create(
            conference=conference,
            display_name="Main Track",
            visibility=TrackVisibility.PUBLIC,
        )
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Proceedings",
            article_source="TEST",
        )
        mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        user = User.objects.create_user(username="reader")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["tracks"][0]["ieee_ecopyright_required"] is True

    def test_track_ieee_ecopyright_not_required_when_exempt(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        conference = Conference.objects.create(
            name="conf",
            display_name="Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        exempt_track = Track.objects.create(
            conference=conference,
            display_name="Workshop",
            visibility=TrackVisibility.PUBLIC,
        )
        Track.objects.create(
            conference=conference,
            display_name="Main Track",
            visibility=TrackVisibility.PUBLIC,
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Proceedings",
            article_source="TEST",
        )
        config.exempt_tracks.add(exempt_track)
        mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        user = User.objects.create_user(username="reader")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        tracks = {t["display_name"]: t for t in response.json()["tracks"]}
        assert tracks["Workshop"]["ieee_ecopyright_required"] is False
        assert tracks["Main Track"]["ieee_ecopyright_required"] is True

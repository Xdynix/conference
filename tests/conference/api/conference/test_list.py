from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceVisibility,
    Track,
    TrackVisibility,
)
from app.conference.services import ConferenceService
from app.core.models import User


@pytest.mark.django_db
class TestListConferences:
    path = reverse("api-1.0.0:list-conferences")

    def test_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        alpha = Conference.objects.create(
            name="alpha-conf",
            display_name="Alpha Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        beta = Conference.objects.create(
            name="beta-conf",
            display_name="Beta Conf",
            visibility=ConferenceVisibility.ADMIN_ONLY,
            registration_enabled=True,
        )
        alpha_tracks = [
            Track.objects.create(
                conference=alpha,
                display_name="Alpha Track",
                visibility=TrackVisibility.PUBLIC,
            )
        ]
        beta_tracks = [
            Track.objects.create(
                conference=beta,
                display_name="Beta Public",
                visibility=TrackVisibility.PUBLIC,
            ),
            Track.objects.create(
                conference=beta,
                display_name="Beta Private",
                visibility=TrackVisibility.ADMIN_ONLY,
            ),
        ]
        mock_visible_conferences = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk__in=[alpha.pk, beta.pk]),
        )
        mock_visible_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.filter(
                pk__in=[alpha_tracks[0].pk, beta_tracks[0].pk],
            ),
        )
        user = User.objects.create_user(username="viewer")
        api_client.force_login(user)

        response = api_client.get(self.path, {"order": "asc"})
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "name": alpha.name,
                    "display_name": alpha.display_name,
                    "visibility": alpha.visibility,
                    "registration_enabled": False,
                    "location": "",
                    "tracks": [
                        {
                            "uid": str(alpha_tracks[0].uid),
                            "display_name": alpha_tracks[0].display_name,
                            "visibility": alpha_tracks[0].visibility,
                            "submissions_enabled": False,
                            "accepts_submissions": False,
                            "ieee_ecopyright_required": False,
                        }
                    ],
                },
                {
                    "name": beta.name,
                    "display_name": beta.display_name,
                    "visibility": beta.visibility,
                    "registration_enabled": True,
                    "location": "",
                    "tracks": [
                        {
                            "uid": str(beta_tracks[0].uid),
                            "display_name": beta_tracks[0].display_name,
                            "visibility": beta_tracks[0].visibility,
                            "submissions_enabled": False,
                            "accepts_submissions": False,
                            "ieee_ecopyright_required": False,
                        },
                    ],
                },
            ],
        }

        mock_visible_conferences.assert_awaited_once_with(user)
        mock_visible_tracks.assert_awaited_once_with(user)

    def test_returns_empty_list_when_service_has_no_results(
        self,
        mocker: MockerFixture,
        api_client: Client,
    ) -> None:
        mock_visible_conferences = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(name="not-exist"),
        )
        mock_visible_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.none(),
        )

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"items": []}

        mock_visible_conferences.assert_awaited_once_with(AnonymousUser())
        mock_visible_tracks.assert_awaited_once_with(AnonymousUser())

    def test_scopes_tracks_to_matching_conference(self, api_client: Client) -> None:
        alpha = Conference.objects.create(
            name="alpha-conf",
            display_name="Alpha Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        beta = Conference.objects.create(
            name="beta-conf",
            display_name="Beta Conf",
            visibility=ConferenceVisibility.PUBLIC,
        )
        alpha_track = Track.objects.create(
            conference=alpha,
            display_name="Alpha Track",
            visibility=TrackVisibility.PUBLIC,
        )
        beta_track = Track.objects.create(
            conference=beta,
            display_name="Beta Track",
            visibility=TrackVisibility.PUBLIC,
        )

        response = api_client.get(self.path, {"order": "asc"})
        assert response.status_code == HTTPStatus.OK

        data = response.json()["items"]
        assert [item["name"] for item in data] == [alpha.name, beta.name]
        tracks_by_conf = {
            item["name"]: [track["display_name"] for track in item["tracks"]]
            for item in data
        }
        assert tracks_by_conf == {
            alpha.name: [alpha_track.display_name],
            beta.name: [beta_track.display_name],
        }

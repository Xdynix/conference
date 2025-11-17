from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.mark.django_db
class TestGetConference:
    @staticmethod
    def path(name: str) -> str:
        return reverse("api-1.0.0:get-conference", args=[name])

    def test_happy_path(self, api_client: Client) -> None:
        conference = Conference.objects.create(
            name="conf",
            display_name="Conf",
            visibility=Conference.Visibility.PUBLIC,
        )
        keyword_texts = ["AI", "Security", "Cloud"]
        conference.keywords.set(
            [Keyword.objects.create(text=text) for text in keyword_texts]
        )
        track = Track.objects.create(
            conference=conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "name": conference.name,
            "display_name": conference.display_name,
            "visibility": conference.visibility,
            "keywords": sorted(keyword_texts),
            "tracks": [
                {
                    "uid": str(track.uid),
                    "display_name": track.display_name,
                    "visibility": track.visibility,
                },
            ],
        }

    def test_anonymous_user_can_read_public_conference(
        self,
        api_client: Client,
    ) -> None:
        conference = Conference.objects.create(
            name="public-conf",
            display_name="Public Conference",
            visibility=Conference.Visibility.PUBLIC,
        )
        public_track = Track.objects.create(
            conference=conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )
        Track.objects.create(
            conference=conference,
            display_name="Hidden Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == conference.name
        assert [track["uid"] for track in data["tracks"]] == [str(public_track.uid)]

    def test_anonymous_user_cannot_read_private_conference(
        self,
        api_client: Client,
    ) -> None:
        conference = Conference.objects.create(
            name="hidden-conf",
            display_name="Hidden Conference",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_can_read_private_conference(
        self,
        api_client: Client,
        track_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username="track-admin")
        conference = Conference.objects.create(
            name="private-conf",
            display_name="Private Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        visible_track = Track.objects.create(
            conference=conference,
            display_name="Visible Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        Track.objects.create(
            conference=conference,
            display_name="Hidden Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        TrackRoleAssignment.objects.create(
            track=visible_track,
            user=user,
            role=track_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [track["uid"] for track in data["tracks"]] == [str(visible_track.uid)]

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_sees_all_tracks(
        self,
        api_client: Client,
        conference_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username="conf-admin")
        conference = Conference.objects.create(
            name="admin-conf",
            display_name="Admin Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        public_track = Track.objects.create(
            conference=conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )
        private_track = Track.objects.create(
            conference=conference,
            display_name="Private Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=conference_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [track["uid"] for track in data["tracks"]] == [
            str(private_track.uid),
            str(public_track.uid),
        ]

    def test_superuser_sees_everything(self, api_client: Client) -> None:
        user = User.objects.create_user(username="root", is_superuser=True)
        conference = Conference.objects.create(
            name="secret-conf",
            display_name="Secret Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        tracks = [
            Track.objects.create(
                conference=conference,
                display_name="Private Track",
                visibility=Track.Visibility.ADMIN_ONLY,
            ),
            Track.objects.create(
                conference=conference,
                display_name="Public Track",
                visibility=Track.Visibility.PUBLIC,
            ),
        ]
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [track["uid"] for track in data["tracks"]] == [
            str(track.uid) for track in tracks
        ]

    @pytest.mark.parametrize("role", (GlobalRole.ADMIN, GlobalRole.READ_ALL))
    def test_global_roles_see_everything(
        self,
        api_client: Client,
        role: GlobalRole,
    ) -> None:
        user = User.objects.create_user(username="global-user")
        GlobalRoleAssignment.objects.create(user=user, role=role)
        conference = Conference.objects.create(
            name="global-conf",
            display_name="Global Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        tracks = [
            Track.objects.create(
                conference=conference,
                display_name="Private Track",
                visibility=Track.Visibility.ADMIN_ONLY,
            ),
            Track.objects.create(
                conference=conference,
                display_name="Public Track",
                visibility=Track.Visibility.PUBLIC,
            ),
        ]
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [track["uid"] for track in data["tracks"]] == [
            str(track.uid) for track in tracks
        ]

    def test_inactive_conference_is_not_visible(self, api_client: Client) -> None:
        user = User.objects.create_superuser(username="owner")
        conference = Conference.objects.create(
            name="inactive-conf",
            display_name="Inactive",
            visibility=Conference.Visibility.PUBLIC,
            active=False,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_tracks_are_filtered(self, api_client: Client) -> None:
        user = User.objects.create_superuser(username="owner")
        conference = Conference.objects.create(
            name="active-conf",
            display_name="Active",
            visibility=Conference.Visibility.PUBLIC,
        )
        active_track = Track.objects.create(
            conference=conference,
            display_name="Visible Track",
            visibility=Track.Visibility.PUBLIC,
            active=True,
        )
        Track.objects.create(
            conference=conference,
            display_name="Inactive Track",
            visibility=Track.Visibility.PUBLIC,
            active=False,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [track["uid"] for track in data["tracks"]] == [
            str(active_track.uid),
        ]

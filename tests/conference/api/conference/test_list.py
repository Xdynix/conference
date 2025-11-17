from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.mark.django_db
class TestListConferences:
    path = reverse("api-1.0.0:list-conferences")

    def test_happy_path(self, api_client: Client) -> None:
        user = User.objects.create_superuser(username="owner")
        alpha = Conference.objects.create(
            name="alpha-conf",
            display_name="Alpha Conf",
            visibility=Conference.Visibility.PUBLIC,
        )
        alpha_track = Track.objects.create(
            conference=alpha,
            display_name="Alpha Track",
            visibility=Track.Visibility.PUBLIC,
        )
        beta = Conference.objects.create(
            name="beta-conf",
            display_name="Beta Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        beta_primary = Track.objects.create(
            conference=beta,
            display_name="Beta Primary",
            visibility=Track.Visibility.PUBLIC,
        )
        beta_secondary = Track.objects.create(
            conference=beta,
            display_name="Beta Secondary",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        api_client.force_login(user)

        response = api_client.get(self.path, {"order": "asc"})
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "items": [
                {
                    "name": alpha.name,
                    "display_name": alpha.display_name,
                    "visibility": alpha.visibility,
                    "tracks": [
                        {
                            "uid": str(alpha_track.uid),
                            "display_name": alpha_track.display_name,
                            "visibility": alpha_track.visibility,
                        }
                    ],
                },
                {
                    "name": beta.name,
                    "display_name": beta.display_name,
                    "visibility": beta.visibility,
                    "tracks": [
                        {
                            "uid": str(beta_primary.uid),
                            "display_name": beta_primary.display_name,
                            "visibility": beta_primary.visibility,
                        },
                        {
                            "uid": str(beta_secondary.uid),
                            "display_name": beta_secondary.display_name,
                            "visibility": beta_secondary.visibility,
                        },
                    ],
                },
            ],
        }

    def test_anonymous_user_sees_only_public_conferences(
        self,
        api_client: Client,
    ) -> None:
        public_conference = Conference.objects.create(
            name="public-conf",
            display_name="Public Conf",
            visibility=Conference.Visibility.PUBLIC,
        )
        public_track = Track.objects.create(
            conference=public_conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )
        Track.objects.create(
            conference=public_conference,
            display_name="Internal Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        private_conference = Conference.objects.create(
            name="hidden-conf",
            display_name="Hidden Conf",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        Track.objects.create(
            conference=private_conference,
            display_name="Hidden Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [public_conference.name]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(public_track.uid),
        ]

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_can_see_private_conference(
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

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [conference.name]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(visible_track.uid),
        ]

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
            display_name="Main Track",
            visibility=Track.Visibility.PUBLIC,
        )
        private_track = Track.objects.create(
            conference=conference,
            display_name="Staff Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=conference_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [conference.name]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(public_track.uid),
            str(private_track.uid),
        ]

    def test_superuser_sees_everything(self, api_client: Client) -> None:
        user = User.objects.create_superuser(username="root")
        public_conference = Conference.objects.create(
            name="public",
            display_name="Public",
            visibility=Conference.Visibility.PUBLIC,
        )
        public_track = Track.objects.create(
            conference=public_conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )
        hidden_track = Track.objects.create(
            conference=public_conference,
            display_name="Hidden Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        private_conference = Conference.objects.create(
            name="private",
            display_name="Private",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        private_public_track = Track.objects.create(
            conference=private_conference,
            display_name="Visible",
            visibility=Track.Visibility.PUBLIC,
        )
        private_hidden_track = Track.objects.create(
            conference=private_conference,
            display_name="Secret",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [
            public_conference.name,
            private_conference.name,
        ]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(hidden_track.uid),
            str(public_track.uid),
        ]
        assert [track["uid"] for track in data["items"][1]["tracks"]] == [
            str(private_hidden_track.uid),
            str(private_public_track.uid),
        ]

    @pytest.mark.parametrize("role", (GlobalRole.ADMIN, GlobalRole.READ_ALL))
    def test_global_admin_roles_see_everything(
        self,
        api_client: Client,
        role: GlobalRole,
    ) -> None:
        user = User.objects.create_user(username=f"global-{role}")
        GlobalRoleAssignment.objects.create(user=user, role=role)
        conference = Conference.objects.create(
            name="hidden",
            display_name="Hidden",
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
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [conference.name]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(private_track.uid),
            str(public_track.uid),
        ]

    def test_inactive_conferences_and_tracks_are_hidden(
        self,
        api_client: Client,
    ) -> None:
        user = User.objects.create_superuser(username="owner")
        active_conference = Conference.objects.create(
            name="visible-conf",
            display_name="Visible Conf",
            visibility=Conference.Visibility.PUBLIC,
        )
        active_track = Track.objects.create(
            conference=active_conference,
            display_name="Active Track",
            visibility=Track.Visibility.PUBLIC,
            active=True,
        )
        Track.objects.create(
            conference=active_conference,
            display_name="Inactive Track",
            visibility=Track.Visibility.PUBLIC,
            active=False,
        )
        Conference.objects.create(
            name="inactive-conf",
            display_name="Inactive Conf",
            visibility=Conference.Visibility.PUBLIC,
            active=False,
        )
        api_client.force_login(user)

        response = api_client.get(self.path, {"order": "asc"})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["name"] for item in data["items"]] == [active_conference.name]
        assert [track["uid"] for track in data["items"][0]["tracks"]] == [
            str(active_track.uid),
        ]

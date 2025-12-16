from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import InvitationService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_number, any_str


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=Conference.Visibility.PUBLIC,
    )


@pytest.fixture
def track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def conference_admin(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.fixture
def mock_visible(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(InvitationService, "visible_invitations")


@pytest.mark.django_db
class TestListInvitations:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-invitations", args=[conference_name])

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        invitation1 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="Alice",
            family_name="Smith",
        )
        keyword = Keyword.objects.create(text="keyword")
        invitation1.interested_keywords.add(keyword)
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation1,
            role=ConferenceRole.REVIEWER,
        )
        invitation2 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="Bob",
            family_name="Jones",
        )
        token1 = InvitationService.get_invitation_token(invitation1)
        token2 = InvitationService.get_invitation_token(invitation2)
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation2,
            track=track,
            role=TrackRole.REVIEWER,
        )
        mock_visible.return_value = Invitation.objects.filter(
            pk__in=[invitation1.pk, invitation2.pk],
        )
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "uid": str(invitation2.uid),
                    "state": Invitation.State.PENDING,
                    "invitee_email": invitation2.invitee_email,
                    "create_time": any_str,
                    "update_time": any_str,
                    "given_name": "Bob",
                    "family_name": "Jones",
                    "affiliation": "",
                    "region_code": "",
                    "desired_paper_count": any_number,
                    "interested_keywords": [],
                    "conference_roles": [],
                    "track_roles": [
                        {
                            "track": str(track.uid),
                            "role": TrackRole.REVIEWER,
                        },
                    ],
                    "email_send_count": 0,
                    "token": token2,
                    "accept_url": f"{settings.INVITATION_ACCEPT_PAGE_URL}#{token2}",
                    "reject_url": f"{settings.INVITATION_REJECT_PAGE_URL}#{token2}",
                },
                {
                    "uid": str(invitation1.uid),
                    "state": Invitation.State.PENDING,
                    "invitee_email": invitation1.invitee_email,
                    "create_time": any_str,
                    "update_time": any_str,
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "",
                    "region_code": "",
                    "desired_paper_count": any_number,
                    "interested_keywords": ["keyword"],
                    "conference_roles": [ConferenceRole.REVIEWER],
                    "track_roles": [],
                    "email_send_count": 0,
                    "token": token1,
                    "accept_url": f"{settings.INVITATION_ACCEPT_PAGE_URL}#{token1}",
                    "reject_url": f"{settings.INVITATION_REJECT_PAGE_URL}#{token1}",
                },
            ],
        }

        mock_visible.assert_awaited_once_with(conference, conference_admin)

    def test_inactive_track_roles_excluded_from_response(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        active_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        inactive_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=active_track,
            role=TrackRole.CHAIR,
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=inactive_track,
            role=TrackRole.SECRETARY,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=invitation.pk)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["items"][0]["track_roles"] == [
            {
                "track": str(active_track.uid),
                "role": TrackRole.CHAIR,
            }
        ]

        mock_visible.assert_awaited_once_with(conference, conference_admin)

    @pytest.mark.parametrize("state", Invitation.State)
    def test_filter_by_state(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        mock_visible: AsyncMock,
        state: Invitation.State,
    ) -> None:
        pending_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        accepted_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            accept_time=timezone.now(),
        )
        rejected_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            reject_time=timezone.now(),
        )
        mock_visible.return_value = Invitation.objects.filter(
            pk__in=[
                pending_invitation.pk,
                accepted_invitation.pk,
                rejected_invitation.pk,
            ],
        )
        api_client.force_login(conference_admin)

        response = api_client.get(
            self.path(conference.name),
            {"state": state},
        )
        assert response.status_code == HTTPStatus.OK

        expected_invitation = {
            Invitation.State.PENDING: pending_invitation,
            Invitation.State.ACCEPTED: accepted_invitation,
            Invitation.State.REJECTED: rejected_invitation,
        }[state]
        data = response.json()
        [invitation_data] = data["items"]
        assert invitation_data["uid"] == str(expected_invitation.uid)
        assert invitation_data["state"] == state

    def test_returns_empty_list_when_no_invitations(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        mock_visible.return_value = Invitation.objects.filter(pk=-1)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["items"] == []

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_admin: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.get(self.path("not-existing-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_visibility_filters_applied(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        mock_visible: AsyncMock,
    ) -> None:
        track_chair = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_chair,
            role=TrackRole.CHAIR,
        )
        visible_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=visible_invitation,
            track=track,
            role=TrackRole.REVIEWER,
        )
        hidden_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        InvitationConferenceRoleEntry.objects.create(
            invitation=hidden_invitation,
            role=ConferenceRole.REVIEWER,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=visible_invitation.pk)
        api_client.force_login(track_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [invitation_data] = data["items"]
        assert invitation_data["uid"] == str(visible_invitation.uid)

        mock_visible.assert_awaited_once_with(conference, track_chair)

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_authenticated_user_without_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        mock_visible: AsyncMock,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=admin,
            role=global_role,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        mock_visible: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        mock_visible: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

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
from app.utils.enums import Region
from tests.helpers import any_str


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
def inviter(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference_admin(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        user=user,
        conference=conference,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.fixture
def mock_visible(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(InvitationService, "visible_invitations")


@pytest.mark.django_db
class TestGetInvitation:
    @classmethod
    def path(cls, conference_name: str, invitation_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-invitation",
            args=[conference_name, invitation_uid],
        )

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        inviter: User,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
            given_name="Alice",
            family_name="Smith",
            affiliation="MIT",
            region_code=Region.US.name,
            desired_paper_count=5,
        )
        keyword = Keyword.objects.create(text="machine-learning")
        invitation.interested_keywords.add(keyword)
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.REVIEWER,
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track,
            role=TrackRole.CHAIR,
        )
        mock_visible.return_value = Invitation.objects.filter(pk=invitation.pk)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(invitation.uid),
            "status": Invitation.Status.PENDING,
            "invitee_email": invitation.invitee_email,
            "create_time": any_str,
            "update_time": any_str,
            "given_name": "Alice",
            "family_name": "Smith",
            "affiliation": "MIT",
            "region_code": "US",
            "desired_paper_count": 5,
            "interested_keywords": ["machine-learning"],
            "conference_roles": [ConferenceRole.REVIEWER],
            "track_roles": [
                {
                    "uid": str(track.uid),
                    "role": TrackRole.CHAIR,
                }
            ],
            "email_send_count": 0,
        }

        mock_visible.assert_awaited_once_with(conference, conference_admin)

    def test_returns_404_when_invitation_not_visible(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        inviter: User,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        mock_visible.return_value = Invitation.objects.none()
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        mock_visible.assert_awaited_once_with(conference, conference_admin)

    def test_returns_404_when_invitation_does_not_exist(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        mock_visible: AsyncMock,
    ) -> None:
        mock_visible.return_value = Invitation.objects.none()
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_admin: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.get(self.path("nonexistent-conference", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        inviter: User,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_authenticated_user_without_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        inviter: User,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        inviter: User,
        mock_visible: AsyncMock,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=admin,
            role=global_role,
        )
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        mock_visible.return_value = Invitation.objects.filter(pk=invitation.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        inviter: User,
        mock_visible: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        mock_visible.return_value = Invitation.objects.filter(pk=invitation.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        inviter: User,
        mock_visible: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        mock_visible.return_value = Invitation.objects.filter(pk=invitation.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.OK

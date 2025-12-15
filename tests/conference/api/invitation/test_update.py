from http import HTTPStatus
from unittest.mock import MagicMock

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
from app.conference.services import InvitationService, KeywordService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import ImmutableInvitation
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=Conference.Visibility.PUBLIC,
    )


@pytest.fixture
def track_a(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def track_b(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def invitation(faker: Faker, conference: Conference) -> Invitation:
    return Invitation.objects.create(
        conference=conference,
        invitee_email=faker.email(),
        given_name="Original",
        family_name="Name",
        affiliation="Original University",
        region_code=Region.GB.name,
        desired_paper_count=5,
    )


@pytest.fixture
def mock_visible(mocker: MockerFixture, invitation: Invitation) -> MagicMock:
    return mocker.patch.object(
        InvitationService,
        "visible_invitations",
        return_value=Invitation.objects.filter(pk=invitation.pk),
    )


@pytest.fixture
def invitation_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(InvitationService, "update_invitation")


@pytest.mark.django_db
class TestUpdateInvitation:
    @classmethod
    def path(cls, conference_name: str, invitation_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-invitation",
            args=[conference_name, invitation_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        track_a: Track,
        track_b: Track,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
    ) -> None:
        keyword_ai = Keyword.objects.create(text="AI")
        keyword_ml = Keyword.objects.create(text="ML")
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.REVIEWER,
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={
                "given_name": "Updated",
                "family_name": "Person",
                "affiliation": "MIT",
                "region_code": "US",
                "desired_paper_count": 15,
                "interested_keywords": ["AI", "ML"],
                "conference_roles": [ConferenceRole.CHAIR, ConferenceRole.SECRETARY],
                "track_roles": [
                    {"track": str(track_a.uid), "role": TrackRole.CHAIR},
                    {"track": str(track_b.uid), "role": TrackRole.REVIEWER},
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["given_name"] == "Updated"
        assert data["family_name"] == "Person"
        assert data["affiliation"] == "MIT"
        assert data["region_code"] == Region.US.name
        assert data["desired_paper_count"] == 15
        assert set(data["interested_keywords"]) == {"AI", "ML"}
        assert set(data["conference_roles"]) == {
            ConferenceRole.CHAIR,
            ConferenceRole.SECRETARY,
        }
        assert len(data["track_roles"]) == 2

        mock_visible.assert_awaited_once_with(conference, global_admin)
        invitation_service_update.assert_called_once_with(
            invitation_uid=invitation.uid,
            user=global_admin,
            given_name="Updated",
            family_name="Person",
            affiliation="MIT",
            region_code=Region.US.name,
            desired_paper_count=15,
            interested_keywords=[keyword_ai, keyword_ml],
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.SECRETARY],
            track_roles={
                track_a: [TrackRole.CHAIR],
                track_b: [TrackRole.REVIEWER],
            },
        )

    def test_trims_whitespace(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        Keyword.objects.create(text="AI")

        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={
                "given_name": "  Alice  ",
                "family_name": "  Smith  ",
                "affiliation": "  MIT  ",
                "interested_keywords": ["  AI  "],
            },
        )

        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["given_name"] == "Alice"
        assert data["family_name"] == "Smith"
        assert data["affiliation"] == "MIT"
        assert data["interested_keywords"] == ["AI"]

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_not_found_when_not_visible(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
    ) -> None:
        mock_visible.return_value = Invitation.objects.none()
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "New"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        invitation_service_update.assert_not_called()

    def test_not_found_for_nonexistent_invitation(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"given_name": "New"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        invitation: Invitation,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path("nonexistent", invitation.uid),
            data={"given_name": "New"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_handle_immutable_invitation(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        mocker.patch.object(
            InvitationService,
            "update_invitation",
            side_effect=ImmutableInvitation("Cannot update accepted invitation"),
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "New"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Cannot update accepted invitation"

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_handle_insufficient_permission(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        mocker.patch.object(
            InvitationService,
            "update_invitation",
            side_effect=InsufficientRolePermission("Insufficient permission"),
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"conference_roles": [ConferenceRole.CHAIR]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert response.json()["message"] == "Insufficient permission"

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_invalid_keyword_returns_422(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Invalid keyword"),
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"interested_keywords": ["invalid"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "interested_keywords"]
        assert error["msg"] == "Invalid keyword"

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_invalid_track_uid_returns_422(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        invalid_uid = ULID()
        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={
                "track_roles": [{"track": str(invalid_uid), "role": TrackRole.CHAIR}],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "track_roles"]
        assert str(invalid_uid) in error["msg"]

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_track_from_wrong_conference_returns_422(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        mocker.patch.object(
            InvitationService,
            "update_invitation",
            side_effect=ValueError("tracks do not belong to this conference"),
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={
                "track_roles": [
                    {"track": str(other_track.uid), "role": TrackRole.CHAIR},
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "track_roles"]
        assert error["msg"] == "tracks do not belong to this conference"

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_omits_lists_preserve_existing_values(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        track_a: Track,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        invitation.interested_keywords.add(keyword)
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.REVIEWER,
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track_a,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "Updated"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["interested_keywords"] == ["AI"]
        assert data["conference_roles"] == [ConferenceRole.REVIEWER]
        assert data["track_roles"] == [
            {"track": str(track_a.uid), "role": TrackRole.CHAIR},
        ]

        mock_visible.assert_awaited_once_with(conference, global_admin)
        invitation_service_update.assert_called_once_with(
            invitation_uid=invitation.uid,
            user=global_admin,
            given_name="Updated",
            family_name=None,
            affiliation=None,
            region_code=None,
            desired_paper_count=None,
            interested_keywords=None,
            conference_roles=None,
            track_roles=None,
        )

    def test_empty_lists_clear_roles_and_keywords(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        track_a: Track,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        invitation.interested_keywords.add(keyword)
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.REVIEWER,
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track_a,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={
                "interested_keywords": [],
                "conference_roles": [],
                "track_roles": [],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["interested_keywords"] == []
        assert data["conference_roles"] == []
        assert data["track_roles"] == []

        mock_visible.assert_awaited_once_with(conference, global_admin)
        invitation_service_update.assert_called_once_with(
            invitation_uid=invitation.uid,
            user=global_admin,
            given_name=None,
            family_name=None,
            affiliation=None,
            region_code=None,
            desired_paper_count=None,
            interested_keywords=[],
            conference_roles=[],
            track_roles={},
        )

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=conference_admin,
            role=conference_role,
        )
        api_client.force_login(conference_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "Updated"},
        )
        assert response.status_code == HTTPStatus.OK

        mock_visible.assert_awaited_once_with(conference, conference_admin)
        invitation_service_update.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        track_a: Track,
        mock_visible: MagicMock,
        invitation_service_update: MagicMock,
        track_role: TrackRole,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        api_client.force_login(track_admin)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "Updated"},
        )
        assert response.status_code == HTTPStatus.OK

        mock_visible.assert_awaited_once_with(conference, track_admin)
        invitation_service_update.assert_called_once()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        invitation_service_update: MagicMock,  # noqa: ARG002
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "Updated"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_no_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        invitation_service_update: MagicMock,  # noqa: ARG002
    ) -> None:
        regular_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(regular_user)

        response = api_client.patch(
            self.path(conference.name, invitation.uid),
            data={"given_name": "Updated"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

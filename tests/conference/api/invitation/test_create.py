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
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import InvitationService, KeywordService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import DuplicateInvitation
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str


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
def invitation_service_create(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(InvitationService, "create_invitation")


@pytest.mark.django_db(transaction=True)
class TestCreateInvitation:
    @classmethod
    def path(cls, name: str) -> str:
        return reverse("api-1.0.0:create-invitation", args=[name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        invitation_service_create: MagicMock,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "alice@example.com",
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "MIT",
                "region_code": "US",
                "desired_paper_count": 10,
                "interested_keywords": ["AI"],
                "conference_roles": [ConferenceRole.REVIEWER],
                "track_roles": [
                    {"uid": str(track_a.uid), "role": TrackRole.CHAIR},
                    {"uid": str(track_a.uid), "role": TrackRole.REVIEWER},
                    {"uid": str(track_b.uid), "role": TrackRole.SECRETARY},
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "uid": any_str,
            "status": Invitation.Status.PENDING,
            "invitee_email": "alice@example.com",
            "create_time": any_str,
            "update_time": any_str,
            "given_name": "Alice",
            "family_name": "Smith",
            "affiliation": "MIT",
            "region_code": "US",
            "desired_paper_count": 10,
            "interested_keywords": ["AI"],
            "conference_roles": [ConferenceRole.REVIEWER],
            "track_roles": [
                {"uid": str(track_a.uid), "role": TrackRole.CHAIR},
                {"uid": str(track_a.uid), "role": TrackRole.REVIEWER},
                {"uid": str(track_b.uid), "role": TrackRole.SECRETARY},
            ],
            "email_send_count": 0,
        }

        invitation_service_create.assert_called_once_with(
            conference=conference,
            inviter=global_admin,
            invitee_email="alice@example.com",
            given_name="Alice",
            family_name="Smith",
            affiliation="MIT",
            region_code="US",
            desired_paper_count=10,
            interested_keywords=[keyword],
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={
                track_a: [TrackRole.CHAIR, TrackRole.REVIEWER],
                track_b: [TrackRole.SECRETARY],
            },
        )

    def test_minimal_payload_uses_defaults(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "minimal@example.com"},
        )
        assert response.status_code == HTTPStatus.CREATED

        invitation = Invitation.objects.get(invitee_email="minimal@example.com")
        assert invitation.given_name == ""
        assert invitation.family_name == ""
        assert invitation.affiliation == ""
        assert invitation.region_code == ""
        assert invitation.desired_paper_count == 5
        assert not invitation.interested_keywords.exists()
        assert not invitation.conference_role_entries.exists()
        assert not invitation.track_role_entries.exists()

    def test_trims_whitespace_from_fields(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        Keyword.objects.create(text="AI")
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "trim@example.com",
                "given_name": "  Alice  ",
                "family_name": "  Smith  ",
                "affiliation": "  MIT  ",
                "interested_keywords": ["  AI  "],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["given_name"] == "Alice"
        assert data["family_name"] == "Smith"
        assert data["affiliation"] == "MIT"
        assert data["interested_keywords"] == ["AI"]

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation_service_create: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=conference_admin,
            role=conference_role,
        )
        api_client.force_login(conference_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "conference-admin@example.com"},
        )
        assert response.status_code == HTTPStatus.CREATED

        invitation_service_create.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track_a: Track,
        invitation_service_create: MagicMock,
        track_role: TrackRole,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        api_client.force_login(track_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "track-admin@example.com"},
        )
        assert response.status_code == HTTPStatus.CREATED

        invitation_service_create.assert_called_once()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        invitation_service_create: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "unauthenticated@example.com"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        invitation_service_create.assert_not_called()

    def test_conference_reviewer_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation_service_create: MagicMock,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.REVIEWER,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "reviewer@example.com"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        invitation_service_create.assert_not_called()

    def test_track_reviewer_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track_a: Track,
        invitation_service_create: MagicMock,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.REVIEWER,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "reviewer@example.com"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        invitation_service_create.assert_not_called()

    def test_handle_unknown_track_uid(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "test@example.com",
                "track_roles": [
                    {"uid": str(ULID()), "role": TrackRole.REVIEWER},
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track_roles"]
        assert "Invalid track UID" in error["msg"]

    def test_handle_unknown_keywords(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: nonexistent."),
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "test@example.com",
                "interested_keywords": ["nonexistent"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "interested_keywords"]
        assert "Unknown keywords" in error["msg"]

    def test_handle_duplicate_invitation(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation_service_create: MagicMock,
    ) -> None:
        invitation_service_create.side_effect = DuplicateInvitation(
            "A pending invitation already exists for this conference and email."
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"invitee_email": "existing@example.com"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "pending invitation already exists" in response.json()["message"]

    def test_handle_track_mismatch(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation_service_create: MagicMock,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        invitation_service_create.side_effect = ValueError(
            "The following tracks do not belong to this conference: Track."
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "test@example.com",
                "track_roles": [
                    {"uid": str(other_track.uid), "role": TrackRole.REVIEWER},
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track_roles"]

    def test_handle_insufficient_permission(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation_service_create: MagicMock,
    ) -> None:
        invitation_service_create.side_effect = InsufficientRolePermission(
            "Conference secretaries can only assign the REVIEWER role."
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "invitee_email": "test@example.com",
                "conference_roles": [ConferenceRole.CHAIR],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert "Conference secretaries can only" in response.json()["message"]

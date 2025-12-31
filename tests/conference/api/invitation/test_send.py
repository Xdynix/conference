from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
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
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import InvitationService
from app.conference.services.invitation import (
    SendInvitationResult,
    SendInvitationStatus,
)
from app.core.models import User


@pytest.fixture(autouse=True)
def invitation_page_urls(settings: LazySettings) -> None:
    settings.INVITATION_ACCEPT_PAGE_URL = "https://example.com/accept"
    settings.INVITATION_REJECT_PAGE_URL = "https://example.com/reject"


@pytest.mark.django_db
class TestPreviewInvitationEmail:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:preview-invitation-email", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Welcome to {{ conference_name }}",
                "body": "Hello {{ given_name }}, click {{ accept_url }} to join.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["format"] == "text"
        assert data["subject"] == "Welcome to Sample Conference"
        assert "Hello John" in data["body"]
        assert "accept" in data["body"]

    def test_default_format_is_text(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["format"] == "text"

    def test_undefined_variable_returns_422(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Hello {{ nonexistent_var }}",
                "body": "Body",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "nonexistent_var" in response.json()["message"]

    def test_invalid_template_syntax_returns_422(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Hello {{ unclosed",
                "body": "Body",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_empty_subject_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"subject": "", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=conference_role,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name),
            data={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(conference=conference, display_name=faker.word())
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestSendInvitations:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:send-invitations", args=[conference_name])

    @pytest.fixture
    def mock_send_invitations(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(InvitationService, "send_invitations")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        mock_send_invitations.return_value = [
            SendInvitationResult(
                invitation=invitation.uid,
                status=SendInvitationStatus.SENT,
                invitee_email=invitation.invitee_email,
            )
        ]
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [result] = data["results"]
        assert result == {
            "invitation": str(invitation.uid),
            "status": SendInvitationStatus.SENT,
            "invitee_email": invitation.invitee_email,
        }

        mock_send_invitations.assert_called_once()
        call_kwargs = mock_send_invitations.call_args.kwargs
        assert call_kwargs["template"].subject == "Invitation"
        assert call_kwargs["template"].body == "Please join"
        assert call_kwargs["force_send_to_rejected"] is False
        assert call_kwargs["force_send_to_recent"] is False

    def test_passes_force_flags_to_service(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        mock_send_invitations.return_value = []
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
                "force_send_to_rejected": True,
                "force_send_to_recent": True,
            },
        )
        assert response.status_code == HTTPStatus.OK

        call_kwargs = mock_send_invitations.call_args.kwargs
        assert call_kwargs["force_send_to_rejected"] is True
        assert call_kwargs["force_send_to_recent"] is True

    def test_deduplicates_invitations(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        mock_send_invitations.return_value = []
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [
                    str(invitation.uid),
                    str(invitation.uid),
                    str(invitation.uid),
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        call_args = mock_send_invitations.call_args
        uids_passed = call_args[0][0]
        assert len(uids_passed) == 1
        assert invitation.uid in uids_passed

    def test_invisible_uid_returns_422(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        nonexistent_uid = ULID()
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid), str(nonexistent_uid)],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "invitations"]
        assert str(nonexistent_uid) in error["msg"]

        mock_send_invitations.assert_not_called()

    def test_empty_invitations_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        mock_send_invitations: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        mock_send_invitations.assert_not_called()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        mock_send_invitations.return_value = []
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=conference_role,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.OK

        mock_send_invitations.assert_called_once()

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        mock_send_invitations.assert_not_called()

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_invitations.assert_not_called()

    def test_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        track = Track.objects.create(conference=conference, display_name=faker.word())
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_invitations.assert_not_called()

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        invitation: Invitation,
        mock_send_invitations: MagicMock,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Please join",
                "invitations": [str(invitation.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_invitations.assert_not_called()

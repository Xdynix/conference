from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services.review import (
    ReviewerNotificationService,
    SendNotificationResult,
    SendNotificationStatus,
)
from app.core.models import User


@pytest.mark.django_db
class TestReviewerPreviewNotificationEmail:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:preview-reviewer-notification-email",
            args=[conference_name],
        )

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
                "subject": "Reminder for {{ conference_name }}",
                "body": (
                    "Hello {{ given_name }}, "
                    "you have {{ pending_review_count }} pending reviews."
                ),
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["format"] == "text"
        assert data["subject"] == "Reminder for CONF-2025"
        assert "Hello John" in data["body"]
        assert "3 pending reviews" in data["body"]

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
class TestSendReviewerNotifications:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:send-reviewer-notifications",
            args=[conference_name],
        )

    @pytest.fixture
    def mock_send_notifications(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(ReviewerNotificationService, "send_notifications")

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        mock_send_notifications.return_value = [
            SendNotificationResult(
                reviewer=conference_reviewer.uid,
                status=SendNotificationStatus.SENT,
                reviewer_email="reviewer@example.com",
            )
        ]
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [result] = data["results"]
        assert result == {
            "reviewer": str(conference_reviewer.uid),
            "status": SendNotificationStatus.SENT,
            "reviewer_email": "reviewer@example.com",
        }

        mock_send_notifications.assert_called_once()
        call_kwargs = mock_send_notifications.call_args.kwargs
        assert call_kwargs["template"].subject == "Review reminder"
        assert call_kwargs["template"].body == "Please review"
        assert call_kwargs["reply_to"] is None
        assert call_kwargs["force_send_to_recent"] is False

    def test_passes_options_to_service(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        mock_send_notifications.return_value = []
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
                "reply_to": "admin@example.com",
                "force_send_to_recent": True,
            },
        )
        assert response.status_code == HTTPStatus.OK

        call_kwargs = mock_send_notifications.call_args.kwargs
        assert call_kwargs["reply_to"] == "admin@example.com"
        assert call_kwargs["force_send_to_recent"] is True

    def test_deduplicates_reviewers(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        mock_send_notifications.return_value = []
        api_client.force_login(global_admin)

        reviewer_uid = str(conference_reviewer.uid)
        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [reviewer_uid, reviewer_uid, reviewer_uid],
            },
        )
        assert response.status_code == HTTPStatus.OK

        call_args = mock_send_notifications.call_args
        uids_passed = call_args[0][1]
        assert len(uids_passed) == 1
        assert conference_reviewer.uid in uids_passed

    def test_empty_reviewers_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        mock_send_notifications: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        mock_send_notifications.assert_not_called()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        mock_send_notifications.return_value = []
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
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.OK

        mock_send_notifications.assert_called_once()

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        mock_send_notifications.assert_not_called()

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_notifications.assert_not_called()

    def test_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
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
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_notifications.assert_not_called()

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        conference_reviewer: User,
        mock_send_notifications: MagicMock,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name),
            data={
                "subject": "Review reminder",
                "body": "Please review",
                "reviewers": [str(conference_reviewer.uid)],
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        mock_send_notifications.assert_not_called()

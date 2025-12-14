from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.mail import EmailMessage
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Conference, Invitation
from app.conference.services.invitation import (
    ImmutableInvitation,
    InvitationEmailContext,
    InvitationService,
    SendInvitationStatus,
)
from app.utils.email import EmailTemplate
from tests.helpers import approx_now, update_object


@pytest.fixture
def template() -> EmailTemplate:
    return EmailTemplate(
        subject="Invitation to {{ conference_name }}",
        body="Hello {{ given_name }}, click {{ accept_url }} to accept.",
    )


@pytest.fixture
def mock_send(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(EmailMessage, "send")


class TestInvitationEmailContextSample:
    def test_happy_path(self, settings: LazySettings) -> None:
        site_name = "Test Site"
        settings.SITE_NAME = site_name

        context = InvitationEmailContext.sample(
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert context.site_name == site_name
        assert context.conference_name == "Sample Conference"
        assert context.conference_display_name == "Sample Conference 2025"
        assert context.given_name == "John"
        assert context.family_name == "Doe"
        assert context.affiliation == "Sample University"
        assert str(context.accept_url) == "https://example.com/accept#sample-token"
        assert str(context.reject_url) == "https://example.com/reject#sample-token"

    def test_context_can_be_used_for_template_rendering(
        self,
        template: EmailTemplate,
    ) -> None:
        context = InvitationEmailContext.sample(
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        rendered = template.render(context)

        assert "Sample Conference" in rendered.subject
        assert "John" in rendered.body
        assert "https://example.com/accept#sample-token" in rendered.body


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceSendInvitation:
    def test_happy_path(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        assert invitation.last_email_sent_time is None
        assert invitation.email_send_count == 0

        sent, invitee_email = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert sent is True
        assert invitee_email == invitation.invitee_email

        invitation.refresh_from_db()
        assert invitation.last_email_sent_time == approx_now()
        assert invitation.email_send_count == 1

        mock_send.assert_called_once()

    def test_increments_send_count_on_subsequent_sends(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        assert invitation.email_send_count == 0

        InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_recent=True,
        )
        InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_recent=True,
        )

        invitation.refresh_from_db()
        assert invitation.email_send_count == 2

        assert mock_send.call_count == 2

    def test_skips_recently_sent(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation, last_email_sent_time=timezone.now())

        sent, invitee_email = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert sent is False
        assert invitee_email == invitation.invitee_email

        mock_send.assert_not_called()

    def test_force_send_to_recent(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation, last_email_sent_time=timezone.now())

        sent, _ = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_recent=True,
        )

        assert sent is True

        mock_send.assert_called_once()

    def test_sends_after_interval_expires(
        self,
        settings: LazySettings,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(
            invitation,
            last_email_sent_time=(
                timezone.now()
                - settings.INVITATION_EMAIL_INTERVAL
                - timedelta(seconds=1)
            ),
        )

        sent, _ = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert sent is True

        mock_send.assert_called_once()

    def test_skips_rejected_invitation(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation, reject_time=timezone.now())

        sent, invitee_email = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert sent is False
        assert invitee_email == invitation.invitee_email

        mock_send.assert_not_called()

    def test_force_send_to_rejected(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation, reject_time=timezone.now())

        sent, _ = InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_rejected=True,
        )

        assert sent is True

        mock_send.assert_called_once()

    def test_raises_for_accepted_invitation(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation, accept_time=timezone.now())

        with pytest.raises(ImmutableInvitation):
            InvitationService.send_invitation(
                invitation.uid,
                template=template,
                invitation_accept_page_url="https://example.com/accept",
                invitation_reject_page_url="https://example.com/reject",
            )

        mock_send.assert_not_called()

    def test_raises_for_nonexistent_invitation(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        with pytest.raises(Invitation.DoesNotExist):
            InvitationService.send_invitation(
                ULID(),
                template=template,
                invitation_accept_page_url="https://example.com/accept",
                invitation_reject_page_url="https://example.com/reject",
            )

        mock_send.assert_not_called()

    def test_passes_cc_to_email(
        self,
        invitation: Invitation,
        template: EmailTemplate,
        mocker: MockerFixture,
    ) -> None:
        mock_build = mocker.patch(
            "app.utils.email.RenderedEmail.build_message",
            return_value=MagicMock(),
        )

        InvitationService.send_invitation(
            invitation.uid,
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            cc=["admin@example.com", "manager@example.com"],
        )

        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["cc"] == [
            "admin@example.com",
            "manager@example.com",
        ]

    def test_uses_database_transaction(
        self,
        mocker: MockerFixture,
        invitation: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        mocker.patch.object(Invitation, "save", side_effect=RuntimeError("Test Error"))

        with pytest.raises(RuntimeError, match="Test Error"):
            InvitationService.send_invitation(
                invitation.uid,
                template=template,
                invitation_accept_page_url="https://example.com/accept",
                invitation_reject_page_url="https://example.com/reject",
            )

        invitation.refresh_from_db()
        assert invitation.last_email_sent_time is None
        assert invitation.email_send_count == 0

        mock_send.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceSendInvitations:
    @pytest.fixture
    def invitation_a(self, faker: Faker, conference: Conference) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="Alice",
        )

    @pytest.fixture
    def invitation_b(self, faker: Faker, conference: Conference) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="Bob",
        )

    def test_happy_path(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
        invitation_a: Invitation,
        invitation_b: Invitation,
    ) -> None:
        results = InvitationService.send_invitations(
            [invitation_a.uid, invitation_b.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        [result_a, result_b] = results
        assert result_a.invitation_uid == invitation_a.uid
        assert result_a.status == SendInvitationStatus.SENT
        assert result_a.invitee_email == invitation_a.invitee_email
        assert result_b.invitation_uid == invitation_b.uid
        assert result_b.status == SendInvitationStatus.SENT
        assert result_b.invitee_email == invitation_b.invitee_email

        assert mock_send.call_count == 2

    def test_empty_list(self, template: EmailTemplate, mock_send: MagicMock) -> None:
        results = InvitationService.send_invitations(
            [],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        assert results == []

        mock_send.assert_not_called()

    def test_not_found_invitation(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
        invitation_a: Invitation,
    ) -> None:
        nonexistent_uid = ULID()

        results = InvitationService.send_invitations(
            [invitation_a.uid, nonexistent_uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        [result_a, result_nonexistent] = results
        assert result_a.invitation_uid == invitation_a.uid
        assert result_a.status == SendInvitationStatus.SENT
        assert result_nonexistent.invitation_uid == nonexistent_uid
        assert result_nonexistent.status == SendInvitationStatus.NOT_FOUND
        assert result_nonexistent.reason is not None

        mock_send.assert_called_once()

    def test_skipped_invitation(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
        invitation_a: Invitation,
        invitation_b: Invitation,
    ) -> None:
        update_object(invitation_b, reject_time=timezone.now())

        results = InvitationService.send_invitations(
            [invitation_a.uid, invitation_b.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        [result_a, result_b] = results
        assert result_a.invitation_uid == invitation_a.uid
        assert result_a.status == SendInvitationStatus.SENT
        assert result_b.invitation_uid == invitation_b.uid
        assert result_b.status == SendInvitationStatus.SKIPPED
        assert result_b.invitee_email == invitation_b.invitee_email
        assert result_b.reason is not None

        mock_send.assert_called_once()

    def test_accepted_invitation_is_skipped(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
        invitation_a: Invitation,
        invitation_b: Invitation,
    ) -> None:
        update_object(invitation_b, accept_time=timezone.now())

        results = InvitationService.send_invitations(
            [invitation_a.uid, invitation_b.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        [result_a, result_b] = results
        assert result_a.invitation_uid == invitation_a.uid
        assert result_a.status == SendInvitationStatus.SENT
        assert result_b.invitation_uid == invitation_b.uid
        assert result_b.status == SendInvitationStatus.SKIPPED
        assert result_b.reason is not None

        mock_send.assert_called_once()

    def test_failure_does_not_affect_others(
        self,
        template: EmailTemplate,
        mock_send: MagicMock,
        invitation_a: Invitation,
        invitation_b: Invitation,
    ) -> None:
        mock_send.side_effect = [
            None,
            RuntimeError("Email server error"),
        ]

        results = InvitationService.send_invitations(
            [invitation_a.uid, invitation_b.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
        )

        [result_a, result_b] = results
        assert result_a.invitation_uid == invitation_a.uid
        assert result_a.status == SendInvitationStatus.SENT
        assert result_b.invitation_uid == invitation_b.uid
        assert result_b.status == SendInvitationStatus.FAILED
        assert result_b.reason is not None

        assert mock_send.call_count == 2

    def test_force_send_to_rejected(
        self,
        invitation_a: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation_a, reject_time=timezone.now())

        results = InvitationService.send_invitations(
            [invitation_a.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_rejected=True,
        )

        [result] = results
        assert result.invitation_uid == invitation_a.uid
        assert result.status == SendInvitationStatus.SENT

        mock_send.assert_called_once()

    def test_force_send_to_recent(
        self,
        invitation_a: Invitation,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        update_object(invitation_a, last_email_sent_time=timezone.now())

        results = InvitationService.send_invitations(
            [invitation_a.uid],
            template=template,
            invitation_accept_page_url="https://example.com/accept",
            invitation_reject_page_url="https://example.com/reject",
            force_send_to_recent=True,
        )

        [result] = results
        assert result.invitation_uid == invitation_a.uid
        assert result.status == SendInvitationStatus.SENT

        mock_send.assert_called_once()

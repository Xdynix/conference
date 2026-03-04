import base64
from http import HTTPStatus
from typing import Any

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from ulid import ULID

from app.conference.models import (
    AcceptanceLetter,
    AttendanceType,
    Conference,
    ConferenceFile,
    EmailSendLog,
    Paper,
    PaperState,
    Receipt,
    Registration,
    RegistrationState,
    Track,
)
from app.core.models import User
from tests.helpers import approx_now, update_object

FAKE_PDF = b"%PDF-fake-content"


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
    )


@pytest.fixture
def acceptance_letter(paper: Paper) -> AcceptanceLetter:
    letter = AcceptanceLetter.objects.create(
        paper=paper,
        template="template",
        context={},
    )
    letter.rendered_pdf.save("letter.pdf", ContentFile(FAKE_PDF), save=True)
    return letter


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="General Attendance",
        paper_required=False,
        admin_only=False,
    )


@pytest.fixture
def registration(
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        attendance_type=attendance_type,
        state=RegistrationState.CONFIRMED,
    )


@pytest.fixture
def receipt(registration: Registration) -> Receipt:
    receipt = Receipt.objects.create(
        registration=registration,
        template="template",
        context={},
    )
    receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)
    return receipt


@pytest.fixture
def conference_file(conference: Conference) -> ConferenceFile:
    cf = ConferenceFile.objects.create(
        conference=conference,
        name="payment-form",
        filename="Payment Form.pdf",
    )
    cf.file.save("Payment Form.pdf", ContentFile(FAKE_PDF), save=True)
    return cf


def make_payload(**overrides: Any) -> dict[str, Any]:
    defaults = {
        "correlation_id": "test-email-001",
        "to": ["alice@example.com"],
        "subject": "Test Subject",
        "body": "Hello, world!",
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.django_db(transaction=True)
class TestSendEmail:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:send-email", args=[conference_name])

    def test_happy_path(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == {
            "sent": True,
            "correlation_id": "test-email-001",
            "send_time": approx_now(),
        }

        [sent_email] = mailoutbox
        assert sent_email.to == ["alice@example.com"]
        assert sent_email.subject == "Test Subject"
        assert sent_email.body == "Hello, world!"

        log = EmailSendLog.objects.get(
            conference=conference,
            correlation_id="test-email-001",
        )
        assert log.sender == conference_chair

    def test_html_format(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(format="html", body="<p>Hello</p>"),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["sent"] is True

        [sent_email] = mailoutbox
        assert sent_email.content_subtype == "html"
        assert sent_email.body == "<p>Hello</p>"

    def test_cc_bcc_reply_to(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                cc=["cc@example.com"],
                bcc=["bcc@example.com"],
                reply_to="reply@example.com",
            ),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["sent"] is True

        [sent_email] = mailoutbox
        assert sent_email.cc == ["cc@example.com"]
        assert sent_email.bcc == ["bcc@example.com"]
        assert sent_email.reply_to == ["reply@example.com"]

    def test_from_name(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        settings: LazySettings,
    ) -> None:
        settings.DEFAULT_FROM_EMAIL = "noreply@example.com"
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(from_name="Program Committee"),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["sent"] is True

        [sent_email] = mailoutbox
        assert sent_email.from_email == "Program Committee <noreply@example.com>"

    def test_subject_sanitized(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(subject="Line1\r\nLine2"),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert "\n" not in sent_email.subject
        assert "\r" not in sent_email.subject

    def test_duplicate_correlation_id_skips_resend(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        first = api_client.post(
            self.path(conference.name),
            data=make_payload(),
        )
        assert first.status_code == HTTPStatus.OK
        assert first.json()["sent"] is True

        second = api_client.post(
            self.path(conference.name),
            data=make_payload(),
        )
        assert second.status_code == HTTPStatus.OK
        assert second.json()["sent"] is False

        assert len(mailoutbox) == 1
        assert EmailSendLog.objects.filter(conference=conference).count() == 1

    def test_force_resend_with_same_correlation_id(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        api_client.post(
            self.path(conference.name),
            data=make_payload(),
        )

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(force=True),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["sent"] is True

        assert len(mailoutbox) == 2
        assert EmailSendLog.objects.filter(conference=conference).count() == 1

    def test_acceptance_letter_attachment(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        acceptance_letter: AcceptanceLetter,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": paper.code},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert len(sent_email.attachments) == 1

    def test_receipt_attachment(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        receipt: Receipt,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "receipt", "registration_uid": str(registration.uid)},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert len(sent_email.attachments) == 1

    def test_conference_file_attachment(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "conference_file", "name": "payment-form"},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert len(sent_email.attachments) == 1

    def test_inline_attachment(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)
        content = base64.b64encode(FAKE_PDF).decode()

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "inline", "filename": "final.pdf", "content": content},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert len(sent_email.attachments) == 1
        filename, attached_content, _ = sent_email.attachments[0]
        assert filename == "final.pdf"
        assert attached_content == FAKE_PDF

    def test_attachment_custom_filename(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {
                        "type": "conference_file",
                        "name": "payment-form",
                        "filename": "custom-name.pdf",
                    },
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        filename, _, __ = sent_email.attachments[0]
        assert filename == "custom-name.pdf"

    def test_inline_attachment_filename_sanitized(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)
        content = base64.b64encode(FAKE_PDF).decode()

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {
                        "type": "inline",
                        "filename": "../../etc/passwd",
                        "content": content,
                    },
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        filename, _, __ = sent_email.attachments[0]
        assert filename == "_.._etc_passwd"

    def test_multiple_attachments(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        acceptance_letter: AcceptanceLetter,  # noqa: ARG002
        conference_file: ConferenceFile,  # noqa: ARG002
    ) -> None:
        content = base64.b64encode(FAKE_PDF).decode()
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": paper.code},
                    {"type": "conference_file", "name": "payment-form"},
                    {"type": "inline", "filename": "extra.pdf", "content": content},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert len(sent_email.attachments) == 3

    def test_nonexistent_paper_attachment_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": "NOPE"},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attachments", 0]
        assert "NOPE" in error["msg"]

        assert mailoutbox == []

    def test_withdrawn_paper_attachment_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        acceptance_letter: AcceptanceLetter,  # noqa: ARG002
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": paper.code},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "withdrawn" in error["msg"].lower()

        assert mailoutbox == []

    def test_unaccepted_paper_attachment_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        acceptance_letter: AcceptanceLetter,  # noqa: ARG002
    ) -> None:
        update_object(paper, state=PaperState.UNDER_REVIEW)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": paper.code},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "not accepted" in error["msg"].lower()

        assert mailoutbox == []

    def test_paper_without_letter_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": "PAPER-001"},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "acceptance letter" in error["msg"].lower()

        assert mailoutbox == []

    def test_nonexistent_registration_attachment_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        fake_uid = str(ULID())
        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "receipt", "registration_uid": fake_uid},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attachments", 0]

        assert mailoutbox == []

    def test_cancelled_registration_receipt_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        receipt: Receipt,  # noqa: ARG002
    ) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "receipt", "registration_uid": str(registration.uid)},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "cancelled" in error["msg"].lower()

        assert mailoutbox == []

    def test_registration_without_receipt_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "receipt", "registration_uid": str(registration.uid)},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "receipt" in error["msg"].lower()

        assert mailoutbox == []

    def test_nonexistent_conference_file_returns_422(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "conference_file", "name": "nonexistent"},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert "nonexistent" in error["msg"]

        assert mailoutbox == []

    def test_multiple_attachment_errors_collected(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "acceptance_letter", "paper_code": "BAD1"},
                    {"type": "conference_file", "name": "bad2"},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        errors = response.json()["details"]
        assert len(errors) == 2
        assert errors[0]["loc"] == ["body", "payload", "attachments", 0]
        assert errors[1]["loc"] == ["body", "payload", "attachments", 1]

        assert mailoutbox == []

    def test_missing_correlation_id(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        payload = make_payload()
        del payload["correlation_id"]
        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_empty_correlation_id(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(correlation_id=""),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_missing_to(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        payload = make_payload()
        del payload["to"]
        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_empty_to_list(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(to=[]),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_missing_subject(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        payload = make_payload()
        del payload["subject"]
        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_missing_body(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        payload = make_payload()
        del payload["body"]
        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_inline_attachment_missing_filename_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)
        content = base64.b64encode(FAKE_PDF).decode()

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {"type": "inline", "content": content},
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_inline_attachment_empty_content_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)
        empty_content = base64.b64encode(b"").decode()

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {
                        "type": "inline",
                        "filename": "empty.pdf",
                        "content": empty_content,
                    },
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_inline_attachment_invalid_base64_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data=make_payload(
                attachments=[
                    {
                        "type": "inline",
                        "filename": "bad.pdf",
                        "content": "not-valid-base64!!!",
                    },
                ],
            ),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_conference_not_found(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path("nonexistent"), data=make_payload())
        assert response.status_code == HTTPStatus.NOT_FOUND

        assert mailoutbox == []

    def test_inactive_conference_not_found(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.NOT_FOUND

        assert mailoutbox == []

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.OK

        [sent_email] = mailoutbox
        assert sent_email.to == ["alice@example.com"]

    def test_authorization_conference_chair(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.OK

        assert mailoutbox

    def test_authorization_conference_secretary(
        self,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.OK

        assert mailoutbox

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(self.path(conference.name), data=make_payload())
        assert response.status_code == HTTPStatus.FORBIDDEN

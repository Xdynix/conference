from collections.abc import Callable
from email.message import MIMEPart
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.mail import EmailMessage, EmailMultiAlternatives, mailers
from django.db import transaction
from post_office.mail import send_queued
from post_office.models import PRIORITY, Attachment, Email
from pytest_mock import MockerFixture

from app.utils.email import (
    MAX_FROM_EMAIL_LENGTH,
    MAX_SUBJECT_LENGTH,
    URGENT_MAIL_HEADERS,
)


def mime_part() -> MIMEPart:
    part = MIMEPart()
    part.set_content("hello")
    return part


@pytest.mark.django_db
class TestEmailBackend:
    @pytest.fixture(autouse=True)
    def queue_backend(self, queue: Path) -> None:
        """Route every test in the class through the queue backend."""

    def test_keeps_template_syntax(self, mailoutbox: list[EmailMessage]) -> None:
        subject = "Re: {{ title }}"
        body = "Dear {% name %}, see {# note #}."
        EmailMessage(subject, body, to=["to@example.com"]).send()

        email = Email.objects.get()
        assert (email.subject, email.message) == (subject, body)

        send_queued()

        [sent] = mailoutbox
        assert (sent.subject, sent.body) == (subject, body)

    def test_html_only_message(self, mailoutbox: list[EmailMessage]) -> None:
        message = EmailMessage("Subject", "<p>Hi</p>", to=["to@example.com"])
        message.content_subtype = "html"
        message.send()

        email = Email.objects.get()
        assert (email.message, email.html_message) == ("", "<p>Hi</p>")

        send_queued()

        [sent] = mailoutbox
        assert sent.content_subtype == "html"
        assert sent.body == "<p>Hi</p>"

    def test_text_with_html_alternative(self, mailoutbox: list[EmailMessage]) -> None:
        message = EmailMultiAlternatives("Subject", "text", to=["to@example.com"])
        message.attach_alternative("<p>html</p>", "text/html")
        message.send()

        send_queued()

        [sent] = mailoutbox
        assert isinstance(sent, EmailMultiAlternatives)
        assert sent.body == "text"
        assert sent.alternatives == [("<p>html</p>", "text/html")]

    @pytest.mark.parametrize(
        ("importance", "priority"),
        [
            pytest.param("high", PRIORITY.high, id="high"),
            pytest.param("Low", PRIORITY.low, id="low_mixed_case"),
            pytest.param("normal", PRIORITY.medium, id="normal"),
        ],
    )
    def test_importance_header_sets_priority(
        self,
        mailoutbox: list[EmailMessage],
        importance: str,
        priority: int,
    ) -> None:
        EmailMessage(
            "Subject",
            "body",
            to=["to@example.com"],
            headers={"Importance": importance},
        ).send()

        assert Email.objects.get().priority == priority

        send_queued()

        [sent] = mailoutbox
        assert sent.extra_headers["Importance"] == importance

    def test_urgent_mail_is_delivered_first(
        self, mailoutbox: list[EmailMessage]
    ) -> None:
        EmailMessage("Bulk", "body", to=["to@example.com"]).send()
        EmailMessage(
            "Urgent", "body", to=["to@example.com"], headers=URGENT_MAIL_HEADERS
        ).send()

        send_queued()

        assert [sent.subject for sent in mailoutbox] == ["Urgent", "Bulk"]

    def test_rejects_other_alternatives(self) -> None:
        message = EmailMultiAlternatives("Subject", "text", to=["to@example.com"])
        message.attach_alternative("BEGIN:VCALENDAR", "text/calendar")

        with pytest.raises(NotImplementedError):
            message.send()

        assert not Email.objects.exists()

    def test_rejects_alternatives_on_html_only_message(self) -> None:
        message = EmailMultiAlternatives("Subject", "<p>Hi</p>", to=["to@example.com"])
        message.content_subtype = "html"
        message.attach_alternative("Hi", "text/plain")

        with pytest.raises(NotImplementedError):
            message.send()

        assert not Email.objects.exists()

    def test_addresses_and_headers(self, mailoutbox: list[EmailMessage]) -> None:
        EmailMessage(
            "Subject",
            "body",
            from_email="Conf Admin <admin@example.com>",
            to=["to@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to=["reply@example.com"],
            headers={"X-Probe": "1"},
        ).send()

        send_queued()

        [sent] = mailoutbox
        assert sent.from_email == "Conf Admin <admin@example.com>"
        assert (sent.to, sent.cc, sent.bcc) == (
            ["to@example.com"],
            ["cc@example.com"],
            ["bcc@example.com"],
        )
        assert sent.extra_headers["Reply-To"] == "reply@example.com"
        assert sent.extra_headers["X-Probe"] == "1"

    def test_message_id_minted_at_enqueue(
        self,
        mailoutbox: list[EmailMessage],
        settings: LazySettings,
    ) -> None:
        EmailMessage("Subject", "body", to=["to@example.com"]).send()

        email = Email.objects.get()
        assert email.message_id.endswith(f"@{settings.POST_OFFICE['MESSAGE_ID_FQDN']}>")

        send_queued()

        [sent] = mailoutbox
        assert sent.extra_headers["Message-ID"] == email.message_id

    def test_attachments_keep_names_and_mimetypes(
        self,
        queue: Path,
        mailoutbox: list[EmailMessage],
    ) -> None:
        message = EmailMessage("Subject", "body", to=["to@example.com"])
        message.attach("letter.pdf", b"%PDF-1", "application/pdf")
        message.attach("letter.pdf", b"%PDF-2", "application/pdf")
        message.attach("notes.txt", "hello", "text/plain")
        message.send()

        email = Email.objects.get()
        stored = list(email.attachments.all())
        assert len(stored) == 3
        for attachment in stored:
            assert Path(attachment.file.path).is_relative_to(queue)

        send_queued()

        [sent] = mailoutbox
        assert sorted(sent.attachments, key=repr) == sorted(
            [
                ("letter.pdf", b"%PDF-1", "application/pdf"),
                ("letter.pdf", b"%PDF-2", "application/pdf"),
                ("notes.txt", "hello", "text/plain"),
            ],
            key=repr,
        )

    def test_long_attachment_names_survive(
        self, mailoutbox: list[EmailMessage]
    ) -> None:
        names = ["a" * 255, "report." + "x" * 60]
        message = EmailMessage("Subject", "body", to=["to@example.com"])
        for name in names:
            message.attach(name, b"content", "application/octet-stream")
        message.send()

        send_queued()

        [sent] = mailoutbox
        assert sorted(attachment.filename for attachment in sent.attachments) == names

    def test_enqueue_is_atomic(self, queue: Path, mocker: MockerFixture) -> None:
        mocker.patch.object(Attachment, "save", side_effect=RuntimeError("disk full"))
        message = EmailMessage("Subject", "body", to=["to@example.com"])
        message.attach("notes.txt", "hello", "text/plain")

        with pytest.raises(RuntimeError, match="disk full"):
            message.send()

        assert not Email.objects.exists()
        assert not [path for path in queue.rglob("*") if path.is_file()]

    def test_rejects_recipients_with_commas(self) -> None:
        message = EmailMessage("Subject", "body", to=['"Doe, John" <j@example.com>'])

        with pytest.raises(NotImplementedError):
            message.send()

        assert not Email.objects.exists()

    @pytest.mark.parametrize(
        "attach",
        [
            pytest.param(lambda message: message.attach(mime_part()), id="mime_part"),
            pytest.param(
                lambda message: message.attach(
                    "inner.eml",
                    EmailMessage("Inner", "body", to=["inner@example.com"]),
                    "message/rfc822",
                ),
                id="message_content",
            ),
            pytest.param(
                lambda message: message.attach(
                    content=b"x", mimetype="application/octet-stream"
                ),
                id="unnamed",
            ),
        ],
    )
    def test_rejects_unsupported_attachments(
        self,
        attach: Callable[[EmailMessage], None],
    ) -> None:
        message = EmailMessage("Subject", "body", to=["to@example.com"])
        attach(message)

        with pytest.raises(NotImplementedError):
            message.send()

        assert not Email.objects.exists()

    def test_no_messages(self) -> None:
        assert mailers["default"].send_messages([]) == 0
        assert not Email.objects.exists()

    def test_columns_hold_the_header_limits(self) -> None:
        assert Email._meta.get_field("subject").max_length >= MAX_SUBJECT_LENGTH
        assert Email._meta.get_field("from_email").max_length >= MAX_FROM_EMAIL_LENGTH


@pytest.mark.django_db(transaction=True)
def test_enqueue_from_on_commit(
    queue: Path,  # noqa: ARG001
    mailoutbox: list[EmailMessage],
) -> None:
    message = EmailMessage("Subject", "body", to=["to@example.com"])
    message.attach("notes.txt", "hello", "text/plain")

    with transaction.atomic():
        transaction.on_commit(message.send)
        assert not Email.objects.exists()
    assert Email.objects.get().attachments.count() == 1

    send_queued()

    [sent] = mailoutbox
    assert sent.attachments == [("notes.txt", "hello", "text/plain")]

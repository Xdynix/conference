from collections.abc import Sequence
from email.message import MIMEPart
from email.mime.base import MIMEBase
from email.utils import make_msgid

from django.core.files.base import ContentFile
from django.core.mail import EmailAttachment, EmailMessage, EmailMultiAlternatives
from django.db import transaction
from post_office.backends import EmailBackend as PostOfficeEmailBackend
from post_office.models import PRIORITY, STATUS, Attachment, Email
from post_office.settings import get_message_id_enabled, get_message_id_fqdn
from post_office.signals import email_queued

DEFAULT_PRIORITY: int = PRIORITY.medium
IMPORTANCE_PRIORITIES: dict[str, int] = {"high": PRIORITY.high, "low": PRIORITY.low}
UNSUPPORTED_ATTACHMENT = (
    "The queue supports only named attachments with str or bytes content."
)


class EmailBackend(PostOfficeEmailBackend):  # type: ignore[misc]
    """Queue messages for post_office without altering them.

    Stores the subject and body verbatim with no template rendering, commits each
    message with its attachments atomically, keeps every attachment under its own name
    and mimetype, and queues an HTML-only message as HTML; post_office's own backend
    guarantees none of these. Attachments other than named str or bytes content,
    alternatives other than text/html, and recipients containing a comma are rejected
    rather than stored lossily. A message whose ``Importance`` header is high or low is
    queued at that priority. Delivery stays with post_office, through
    ``POST_OFFICE["DEFAULT_MAILER"]``.

    Subclassing post_office's backend is what lets post_office and the deployment check
    recognize this mailer as a queue; only its no-op ``open`` and ``close`` are
    inherited.
    """

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        """Queue the messages. Returns 0 because nothing has been delivered yet.

        Attachment files are written here, inside the caller's transaction if there is
        one; a rollback after this returns leaves them on disk.
        """
        if not email_messages:
            return 0
        stored: list[Attachment] = []
        try:
            with transaction.atomic():
                emails = [self.queue(message, stored) for message in email_messages]
        except Exception:
            for attachment in stored:
                attachment.file.delete(save=False)
            raise
        email_queued.send(sender=Email, emails=emails)
        return 0

    # Mirrors post_office.backends.EmailBackend.send_messages together with
    # post_office.mail.create and post_office.utils.create_attachments; diff against
    # those when upgrading post_office.
    @classmethod
    def queue(cls, message: EmailMessage, stored: list[Attachment]) -> Email:
        """Store ``message`` as a queued ``Email``.

        Each attachment is appended to ``stored`` as soon as its file is written, so a
        failure later in the message still lets the caller delete the file.
        """
        if any("," in address for address in (*message.to, *message.cc, *message.bcc)):
            raise NotImplementedError(
                "The queue cannot store a recipient containing a comma."
            )
        text, html = cls.split_body(message)
        headers = dict(message.extra_headers)
        if message.reply_to:
            headers.setdefault("Reply-To", ", ".join(message.reply_to))
        email = Email.objects.create(
            from_email=message.from_email,
            to=message.to,
            cc=message.cc,
            bcc=message.bcc,
            subject=message.subject,
            message=text,
            html_message=html,
            headers=headers,
            priority=cls.priority_for(headers),
            status=STATUS.queued,
            message_id=(
                make_msgid(domain=get_message_id_fqdn())
                if get_message_id_enabled()
                else None
            ),
        )
        attachments = [
            cls.store_attachment(attachment, stored)
            for attachment in message.attachments
        ]
        if attachments:
            email.attachments.add(*attachments)
        return email

    @classmethod
    def priority_for(cls, headers: dict[str, str]) -> int:
        """Map the standard ``Importance`` header to a queue priority."""
        importance = next(
            (value for name, value in headers.items() if name.lower() == "importance"),
            "",
        )
        return IMPORTANCE_PRIORITIES.get(importance.lower(), DEFAULT_PRIORITY)

    @classmethod
    def split_body(cls, message: EmailMessage) -> tuple[str, str]:
        """Return the plain-text and HTML parts; either may be empty."""
        alternatives = (
            message.alternatives if isinstance(message, EmailMultiAlternatives) else []
        )
        if message.content_subtype == "html":
            if alternatives:
                raise NotImplementedError(
                    "The queue cannot store alternatives on an HTML-only message."
                )
            return "", str(message.body)
        html = ""
        for content, mimetype in alternatives:
            if mimetype != "text/html":
                raise NotImplementedError(
                    "The queue supports only text/html alternatives."
                )
            html = str(content)
        return str(message.body), html

    @classmethod
    def store_attachment(
        cls,
        attachment: EmailAttachment | MIMEBase | MIMEPart,
        stored: list[Attachment],
    ) -> Attachment:
        if not isinstance(attachment, EmailAttachment) or not attachment.filename:
            raise NotImplementedError(UNSUPPORTED_ATTACHMENT)
        content = attachment.content
        if isinstance(content, str):
            content = content.encode()
        if not isinstance(content, bytes):
            raise NotImplementedError(UNSUPPORTED_ATTACHMENT)
        record = Attachment(name=attachment.filename, mimetype=attachment.mimetype)
        # post_office builds the upload path from this name's extension and caps its
        # length, so the caller's filename is kept in ``name`` only.
        record.file.save("attachment.bin", ContentFile(content), save=False)
        stored.append(record)
        record.save()
        return record

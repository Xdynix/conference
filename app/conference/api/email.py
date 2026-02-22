from pathlib import Path
from typing import Annotated, Any, Literal

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import aget_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import ValidationError
from pydantic import AwareDatetime, Base64Bytes, Field, field_validator
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    AcceptanceLetter,
    Conference,
    ConferenceRole,
    PaperState,
    Receipt,
    RegistrationState,
)
from app.conference.models.email import EmailSendLog
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest, EmailStr
from app.infra.models import Mutex
from app.utils.sanitization import sanitize_email_subject, sanitize_filename

router = Router(tags=["Email"], exclude_none=True)


correlation_id_field = EmailSendLog._meta.get_field("correlation_id")


class AttachmentRefBase(Schema):
    type: str
    filename: str | None = None

    @field_validator("filename", mode="after")
    @classmethod
    def _sanitize_filename(cls, v: str | None) -> str | None:
        if v is None:  # pragma: no cover
            return None
        return sanitize_filename(v)

    async def resolve(
        self,
        conference: Conference,
    ) -> tuple[str, bytes]:  # pragma: no cover
        """Resolve to (filename, content_bytes).

        Raises ``ValueError`` if the reference is invalid or inaccessible.
        """
        raise NotImplementedError


class AcceptanceLetterRef(AttachmentRefBase):
    type: Literal["acceptance_letter"]
    paper_code: str

    async def resolve(self, conference: Conference) -> tuple[str, bytes]:
        paper = await conference.papers.active().filter(code=self.paper_code).afirst()
        if not paper:
            raise ValueError(f"Paper {self.paper_code} not found.")
        if paper.withdraw_time is not None:
            raise ValueError(f"Paper {self.paper_code} is withdrawn.")

        accepted_states = {PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED}
        if paper.state not in accepted_states:
            raise ValueError(f"Paper {self.paper_code} is not accepted.")

        letter = await AcceptanceLetter.objects.filter(paper=paper).afirst()
        if not letter:
            raise ValueError(f"No acceptance letter for paper {self.paper_code}.")

        filename = self.filename or Path(letter.rendered_pdf.name).name
        content = await sync_to_async(letter.rendered_pdf.read)()
        return filename, content


class ReceiptRef(AttachmentRefBase):
    type: Literal["receipt"]
    registration_uid: ULID

    async def resolve(self, conference: Conference) -> tuple[str, bytes]:
        registration = await conference.registrations.filter(
            uid=self.registration_uid,
        ).afirst()
        if not registration:
            raise ValueError(f"Registration {self.registration_uid} not found.")
        if registration.state == RegistrationState.CANCELLED:
            raise ValueError(f"Registration {self.registration_uid} is cancelled.")

        receipt = await Receipt.objects.filter(registration=registration).afirst()
        if not receipt:
            raise ValueError(f"No receipt for registration {self.registration_uid}.")

        filename = self.filename or Path(receipt.rendered_pdf.name).name
        content = await sync_to_async(receipt.rendered_pdf.read)()
        return filename, content


class ConferenceFileRef(AttachmentRefBase):
    type: Literal["conference_file"]
    name: str

    async def resolve(self, conference: Conference) -> tuple[str, bytes]:
        conf_file = await conference.files.filter(name=self.name).afirst()
        if not conf_file:
            raise ValueError(f"Conference file {self.name} not found.")

        filename = self.filename or conf_file.filename
        content = await sync_to_async(conf_file.file.read)()
        return filename, content


class InlineRef(AttachmentRefBase):
    type: Literal["inline"]
    filename: str
    content: Base64Bytes = Field(
        min_length=1,
        max_length=settings.MAX_CONFERENCE_FILE_SIZE,
    )

    async def resolve(self, conference: Conference) -> tuple[str, bytes]:  # noqa: ARG002
        return self.filename, self.content


AttachmentRef = Annotated[
    AcceptanceLetterRef | ReceiptRef | ConferenceFileRef | InlineRef,
    Field(discriminator="type"),
]


class SendEmailRequest(Schema):
    correlation_id: str = Field(
        min_length=1,
        max_length=correlation_id_field.max_length,
        description=str(correlation_id_field.help_text),
    )
    force: bool = False
    to: list[EmailStr] = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)
    format: Literal["text", "html"] = "text"
    cc: list[EmailStr] = Field(default_factory=list, max_length=100)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=100)
    reply_to: EmailStr | None = None
    attachments: list[AttachmentRef] = Field(default_factory=list, max_length=20)


class SendEmailResponse(Schema):
    sent: bool
    correlation_id: str
    send_time: AwareDatetime


async def resolve_attachments(
    conference: Conference,
    attachments: list[AttachmentRef],
) -> list[tuple[str, bytes]]:
    """Resolve all attachment references, collecting errors for invalid ones.

    Resolvers raise ``ValueError`` for expected validation failures (e.g. not found,
    inaccessible, wrong conference). The error dicts built here mirror the structure
    used by ``make_validation_error`` and Django Ninja's ``ValidationError`` handler.
    """
    resolved: list[tuple[str, bytes]] = []
    errors: list[dict[str, Any]] = []

    for i, ref in enumerate(attachments):
        try:
            resolved.append(await ref.resolve(conference))
        except ValueError as exc:
            errors.append(
                {
                    "type": "value_error",
                    "loc": ["body", "payload", "attachments", i],
                    "msg": str(exc),
                }
            )

    if errors:
        raise ValidationError(errors=errors)

    return resolved


async def build_email_message(
    payload: SendEmailRequest,
    conference: Conference,
) -> EmailMessage:
    """Build a Django ``EmailMessage`` from the request payload.

    Resolves attachment references and validates them before composing. Raises
    ``ValidationError`` if any attachment reference is invalid.
    """
    subject = sanitize_email_subject(payload.subject)
    reply_to = [payload.reply_to] if payload.reply_to else []

    resolved = await resolve_attachments(conference, payload.attachments)

    message = EmailMessage(
        subject=subject,
        body=payload.body,
        to=payload.to,
        cc=payload.cc,
        bcc=payload.bcc,
        reply_to=reply_to,
    )
    if payload.format == "html":
        message.content_subtype = "html"

    for filename, content in resolved:
        message.attach(filename, content)

    return message


def send_and_log(
    *,
    conference: Conference,
    sender: User,
    payload: SendEmailRequest,
    message: EmailMessage,
) -> tuple[EmailSendLog, bool]:
    """Check idempotency, send the email, and create or update the log entry.

    Returns the log entry and whether the email was sent (``False`` if skipped).
    """
    with Mutex.lock_in_transaction(
        f"{conference.pk}:{payload.correlation_id}",
        namespace="email_send_log",
    ):
        existing = conference.email_send_logs.filter(
            correlation_id=payload.correlation_id,
        ).first()

        if existing and not payload.force:
            return existing, False

        transaction.on_commit(message.send)

        now = timezone.now()

        if existing:
            existing.send_time = now
            existing.sender = sender
            existing.save(update_fields=["send_time", "sender", "update_time"])
            return existing, True

        log_entry = conference.email_send_logs.create(
            correlation_id=payload.correlation_id,
            send_time=now,
            sender=sender,
        )
        return log_entry, True


@router.post(
    "/conferences/{slug:conference_name}/emails:send",
    response=SendEmailResponse,
    summary="Send Email",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def send_email(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: SendEmailRequest,
) -> dict[str, Any]:
    """Send a single email with optional attachments.

    Uses the correlation ID for idempotency: re-sending with the same ID is skipped
    unless ``force`` is set. Attachments are resolved by type and validated before
    sending.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    user = await request.auser()

    message = await build_email_message(payload, conference)
    log_entry, sent = await sync_to_async(send_and_log)(
        conference=conference,
        sender=user,
        payload=payload,
        message=message,
    )

    await audit(
        request=request,
        action=AuditAction.EMAIL_SEND,
        resource=log_entry,
        scope=conference_name,
        payload=payload,
        detail={"sent": sent},
    )

    return {
        "sent": sent,
        "correlation_id": log_entry.correlation_id,
        "send_time": log_entry.send_time,
    }

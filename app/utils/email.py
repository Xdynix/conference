"""Reusable email utilities with Pydantic-based types and template rendering.

This module provides a type-safe email system with:

- **EmailTemplate**: Define email templates with format-specific syntax (e.g., Jinja2).
  Syntax errors are caught at construction time.
- **EmailContext**: Base class for context models. Subclass to define available
  template variables with type safety.
- **RenderedEmail**: A fully rendered email that can build Django ``EmailMessage``
  instances for sending.
- **EmailFormat**: Extensible format handlers (text, HTML, Markdown) that control
  template rendering and message building.

Example usage::

    class InvitationEmailContext(EmailContext):
        site_name: str
        conference_name: str
        accept_link: str

    template = EmailTemplate(
        subject="Invitation to {{ conference_name }}",
        body="Hello, please visit {{ accept_link }} to accept.",
    )

    context = InvitationEmailContext(
        site_name="ConfSys",
        conference_name="PyCon 2025",
        accept_link="https://example.com/accept#token",
    )

    rendered = template.render(context)
    rendered.build_message(to="user@example.com").send()
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from django.core.mail import EmailMessage as DjangoEmailMessage
from jinja2 import StrictUndefined, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from app.utils.sanitization import sanitize_email_subject


class EmailFormat(ABC):
    """Base class for email format handlers.

    Subclass to define how different content formats (text, HTML, Markdown) render
    templates and build email messages.
    """

    @classmethod
    @abstractmethod
    def build_message(
        cls,
        subject: str,
        body: str,
        *,
        to: Sequence[str],
        cc: Sequence[str],
        bcc: Sequence[str],
        from_email: str | None,
    ) -> DjangoEmailMessage:
        """Build a Django ``EmailMessage`` from rendered content."""

    @classmethod
    @abstractmethod
    def render(cls, template: str, context: dict[str, Any]) -> str:
        """Render a template string with context."""

    @classmethod
    def validate_template(cls, template: str) -> str | None:  # noqa: ARG003  # pragma: no cover
        """Validate template syntax. Returns error message or None if valid.

        Default implementation does nothing. Override in subclasses that need template
        validation (e.g., Jinja2-based formats).
        """
        return None


class TextFormat(EmailFormat):
    """Plain text email format using Jinja2 for template rendering."""

    jinja_env = SandboxedEnvironment(
        autoescape=False,
        undefined=StrictUndefined,
    )

    @classmethod
    def build_message(
        cls,
        subject: str,
        body: str,
        *,
        to: Sequence[str],
        cc: Sequence[str],
        bcc: Sequence[str],
        from_email: str | None,
    ) -> DjangoEmailMessage:
        return DjangoEmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=to,
            cc=cc,
            bcc=bcc,
        )

    @classmethod
    def render(cls, template: str, context: dict[str, Any]) -> str:
        return cls.jinja_env.from_string(template).render(context)

    @classmethod
    def validate_template(cls, template: str) -> str | None:
        try:
            cls.jinja_env.from_string(template)
            return None
        except TemplateSyntaxError as exc:
            return str(exc)


class EmailFormatName(StrEnum):
    TEXT = "text"


EMAIL_FORMATS: dict[EmailFormatName, type[EmailFormat]] = {
    EmailFormatName.TEXT: TextFormat,
}

# TODO: Add HTML format.
# TODO: Add Markdown format.


class EmailContext(BaseModel):
    """Base class for email context models.

    Subclass to define available template variables for each email type. Uses
    ``extra="forbid"`` to catch typos in context field names.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class RenderedEmail(BaseModel):
    """A fully rendered email ready to send."""

    model_config = ConfigDict(frozen=True)

    format: EmailFormatName
    subject: str
    body: str

    def build_message(
        self,
        *,
        to: str | Sequence[str],
        cc: str | Sequence[str] = (),
        bcc: str | Sequence[str] = (),
        from_email: str | None = None,
    ) -> DjangoEmailMessage:
        """Build a Django ``EmailMessage`` for sending."""
        if isinstance(to, str):
            to = [to]
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        format_cls = EMAIL_FORMATS[self.format]
        return format_cls.build_message(
            subject=self.subject,
            body=self.body,
            to=to,
            cc=cc,
            bcc=bcc,
            from_email=from_email,
        )

    @field_validator("format", mode="after")
    @classmethod
    def _validate_format(cls, name: EmailFormatName) -> EmailFormatName:
        if name not in EMAIL_FORMATS:
            raise ValueError(f"Unregistered email format: {name!r}.")
        return name

    @field_validator("subject", mode="after")
    @classmethod
    def _sanitize_subject(cls, subject: str) -> str:
        return sanitize_email_subject(subject)


class EmailTemplate(BaseModel):
    """An email template using format-specific syntax.

    Syntax errors are raised at construction. Missing variables are raised at render
    time (e.g., ``jinja2.UndefinedError`` for Jinja2-based formats).
    """

    model_config = ConfigDict(frozen=True)

    format: EmailFormatName = EmailFormatName.TEXT
    subject: str
    body: str

    @field_validator("format", mode="after")
    @classmethod
    def _validate_format(cls, name: EmailFormatName) -> EmailFormatName:
        if name not in EMAIL_FORMATS:
            raise ValueError(f"Unregistered email format: {name!r}.")
        return name

    @field_validator("subject", "body", mode="after")
    @classmethod
    def _validate_template_syntax(cls, value: str, info: ValidationInfo) -> str:
        format_name = info.data.get("format")
        if format_name is None:
            # Format validation failed; skip template validation.
            return value
        format_cls = EMAIL_FORMATS[format_name]
        if error := format_cls.validate_template(value):
            raise ValueError(error)
        return value

    @classmethod
    def from_files(
        cls,
        *,
        subject_path: Path,
        body_path: Path,
        format_: EmailFormatName = EmailFormatName.TEXT,
    ) -> Self:
        """Load template content from files.

        Args:
            subject_path: Path to the subject template file.
            body_path: Path to the body template file.
            format_: Email format to use (defaults to TEXT).

        Returns:
            An ``EmailTemplate`` instance with content loaded from files.
        """
        subject = Path(subject_path).read_text().strip()
        body = Path(body_path).read_text()
        return cls(format=format_, subject=subject, body=body)

    def render(self, context: EmailContext) -> RenderedEmail:
        """Render the template with the given context."""
        format_cls = EMAIL_FORMATS[self.format]
        context_dict = context.model_dump()

        subject = format_cls.render(self.subject, context_dict)
        body = format_cls.render(self.body, context_dict)

        return RenderedEmail(
            format=self.format,
            subject=subject,
            body=body,
        )

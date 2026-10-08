"""Reusable email utilities with Pydantic-based types and template rendering.

This module provides a type-safe email system with:

- **EmailTemplate**: Define email templates with format-specific syntax (e.g., Jinja2).
  Syntax errors are caught at construction time.
- **EmailContext**: Base class for context models. Subclass to define available
  template variables with type safety.
- **RenderedEmail**: A fully rendered email that can build Django ``EmailMessage``
  instances for sending.
- **EmailFormat**: Extensible format handlers (text, Markdown) that control template
  rendering.

Example usage::

    class InvitationEmailContext(EmailContext):
        site_name: str
        conference_name: str
        accept_url: str

    template = EmailTemplate(
        subject="Invitation to {{ conference_name }}",
        body="Hello, please visit {{ accept_url }} to accept.",
    )

    context = InvitationEmailContext(
        site_name="ConfSys",
        conference_name="PyCon 2025",
        accept_url="https://example.com/accept#token",
    )

    rendered = template.render(context)
    rendered.build_message(to="user@example.com").send()
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from django.core.mail import EmailMultiAlternatives
from jinja2 import StrictUndefined, TemplateError, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import AnyUrl, BaseModel, ConfigDict, ValidationInfo, field_validator

from app.utils.markdown import escape as escape_markdown
from app.utils.markdown import render as render_markdown
from app.utils.sanitization import sanitize_email_subject


class EmailFormat(ABC):
    """Base class for email format handlers.

    Subclass to define how a content format renders templates. Formats that produce
    HTML override ``render_html``; the rendered email then carries it as an
    alternative to the plain-text body.
    """

    @classmethod
    @abstractmethod
    def render(cls, template: str, context: dict[str, Any]) -> str:
        """Render a template string to plain text."""

    @classmethod
    def render_html(cls, template: str, context: dict[str, Any]) -> str | None:  # noqa: ARG003
        """Render a template string to HTML. Returns ``None`` for text-only formats."""
        return None

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
    def render(cls, template: str, context: dict[str, Any]) -> str:
        return cls.jinja_env.from_string(template).render(context)

    @classmethod
    def validate_template(cls, template: str) -> str | None:
        try:
            cls.jinja_env.from_string(template)
            return None
        except TemplateSyntaxError as exc:
            return str(exc)


def _escape_markdown_value(value: object) -> object:
    return value if isinstance(value, AnyUrl) else escape_markdown(str(value))


class MarkdownFormat(TextFormat):
    """Markdown email format with a plain-text body and an HTML alternative.

    The text part is the Markdown source and the HTML part is its rendering; the
    subject is always plain text. Context values are escaped in the HTML part, so
    user-supplied text renders literally rather than as Markdown or HTML. Type URL
    fields as ``HttpUrl`` in the context model so they are output verbatim and
    autolink, and do not wrap them in ``_``, which linkify would absorb into the URL.
    """

    html_jinja_env = SandboxedEnvironment(
        autoescape=False,
        undefined=StrictUndefined,
        finalize=_escape_markdown_value,
    )

    @classmethod
    def render_html(cls, template: str, context: dict[str, Any]) -> str:
        markdown = cls.html_jinja_env.from_string(template).render(context)
        return render_markdown(markdown)


class EmailFormatName(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"


EMAIL_FORMATS: dict[EmailFormatName, type[EmailFormat]] = {
    EmailFormatName.TEXT: TextFormat,
    EmailFormatName.MARKDOWN: MarkdownFormat,
}

# TODO: Add HTML format.


MAX_RENDERED_BODY_LENGTH = 100_000


class EmailRenderError(ValueError):
    """Raised when a template cannot be rendered with the given context.

    The message describes the template problem (an undefined variable, a sandbox
    violation, an oversized body) and is safe to show to the template's author.
    """


class RenderedBodyTooLongError(EmailRenderError):
    """Raised when a rendered email body exceeds ``MAX_RENDERED_BODY_LENGTH``."""


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
    html: str | None = None

    def build_message(
        self,
        *,
        to: str | Sequence[str],
        cc: str | Sequence[str] = (),
        bcc: str | Sequence[str] = (),
        reply_to: str | Sequence[str] = (),
        from_email: str | None = None,
    ) -> EmailMultiAlternatives:
        """Build a Django email message, with the HTML body as an alternative part."""
        if isinstance(to, str):
            to = [to]
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        if isinstance(reply_to, str):
            reply_to = [reply_to]
        message = EmailMultiAlternatives(
            subject=self.subject,
            body=self.body,
            from_email=from_email,
            to=to,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
        )
        if self.html is not None:
            message.attach_alternative(self.html, "text/html")
        return message

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
        format: EmailFormatName = EmailFormatName.TEXT,
    ) -> Self:
        """Load template content from files.

        Args:
            subject_path: Path to the subject template file.
            body_path: Path to the body template file.
            format: Email format to use (defaults to TEXT).

        Returns:
            An ``EmailTemplate`` instance with content loaded from files.
        """
        subject = Path(subject_path).read_text().strip()
        body = Path(body_path).read_text()
        return cls(format=format, subject=subject, body=body)

    def render(self, context: EmailContext) -> RenderedEmail:
        """Render the template with the given context.

        Raises ``EmailRenderError`` when the template fails at render time, including
        ``RenderedBodyTooLongError`` when the rendered body exceeds
        ``MAX_RENDERED_BODY_LENGTH``; a template can expand far beyond its own size.
        """
        format_cls = EMAIL_FORMATS[self.format]
        context_dict = context.model_dump()
        try:
            body = format_cls.render(self.body, context_dict)
            if len(body) > MAX_RENDERED_BODY_LENGTH:
                raise RenderedBodyTooLongError(
                    f"Rendered body exceeds {MAX_RENDERED_BODY_LENGTH} characters."
                )
            subject = format_cls.render(self.subject, context_dict)
            html = format_cls.render_html(self.body, context_dict)
        except (TemplateError, OverflowError) as exc:
            # The sandbox reports an oversized range as a plain OverflowError.
            raise EmailRenderError(str(exc)) from exc
        return RenderedEmail(format=self.format, subject=subject, body=body, html=html)

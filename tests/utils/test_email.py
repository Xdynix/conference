from pathlib import Path
from typing import Any

import pytest
from django.core.mail import EmailMessage
from jinja2 import UndefinedError
from pytest_mock import MockerFixture

from app.utils.email import (
    EMAIL_FORMATS,
    EmailContext,
    EmailFormatName,
    EmailTemplate,
    RenderedEmail,
    TextFormat,
)


class TestTextFormat:
    def test_render_simple(self) -> None:
        template = "Hello {{ name }}"
        context = {"name": "World"}
        assert TextFormat.render(template, context) == "Hello World"

    def test_render_missing_variable_raises_error(self) -> None:
        template = "Hello {{ name }}"
        context: dict[str, Any] = {}
        with pytest.raises(UndefinedError):
            TextFormat.render(template, context)

    def test_validate_template_valid(self) -> None:
        assert TextFormat.validate_template("Hello {{ name }}") is None

    def test_validate_template_invalid(self) -> None:
        error = TextFormat.validate_template("Hello {{ name")
        assert error is not None
        assert "unexpected end of template" in error

    def test_build_message(self) -> None:
        msg = TextFormat.build_message(
            subject="Test Subject",
            body="Test Body",
            to=["user@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            from_email="admin@example.com",
        )
        assert isinstance(msg, EmailMessage)
        assert msg.subject == "Test Subject"
        assert msg.body == "Test Body"
        assert msg.to == ["user@example.com"]
        assert msg.cc == ["cc@example.com"]
        assert msg.bcc == ["bcc@example.com"]
        assert msg.from_email == "admin@example.com"
        assert msg.content_subtype == "plain"


class TestEmailContext:
    def test_context_validation(self) -> None:
        class MyContext(EmailContext):
            name: str

        MyContext.model_validate({"name": "test"})
        with pytest.raises(ValueError):
            MyContext.model_validate({"name": "test", "extra": "fail"})


class TestEmailTemplate:
    def test_template_validation_success(self) -> None:
        EmailTemplate(
            format=EmailFormatName.TEXT,
            subject="Hello {{ name }}",
            body="Body {{ content }}",
        )

    def test_template_validation_failure(self) -> None:
        with pytest.raises(ValueError, match="unexpected end of template"):
            EmailTemplate(
                format=EmailFormatName.TEXT,
                subject="Hello {{ name",
                body="Body",
            )

    def test_invalid_format(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(EMAIL_FORMATS, clear=True)
        with pytest.raises(ValueError, match="Unregistered email format"):
            EmailTemplate(
                format=EmailFormatName.TEXT,
                subject="Hello {{ name }}",
                body="Body",
            )

    def test_render(self) -> None:
        class MyContext(EmailContext):
            name: str
            content: str

        template = EmailTemplate(
            format=EmailFormatName.TEXT,
            subject="Hello {{ name }}",
            body="Body {{ content }}",
        )
        context = MyContext(name="User", content="Content")
        rendered = template.render(context)
        assert isinstance(rendered, RenderedEmail)
        assert rendered.subject == "Hello User"
        assert rendered.body == "Body Content"
        assert rendered.format == EmailFormatName.TEXT

    def test_from_files(self, tmp_path: Path) -> None:
        subject_file = tmp_path / "subject.txt"
        body_file = tmp_path / "body.txt"

        subject_file.write_text("Subject {{ var }}\n\n")
        body_file.write_text("Body content\n")

        template = EmailTemplate.from_files(
            subject_path=subject_file,
            body_path=body_file,
            format=EmailFormatName.TEXT,
        )
        assert template.subject == "Subject {{ var }}"
        assert template.body == "Body content\n"
        assert template.format == EmailFormatName.TEXT


class TestRenderedEmail:
    def test_subject_sanitization(self) -> None:
        rendered = RenderedEmail(
            format=EmailFormatName.TEXT,
            subject="Hello\nWorld",
            body="Body",
        )
        assert rendered.subject == "HelloWorld"

    def test_build_message(self) -> None:
        rendered = RenderedEmail(
            format=EmailFormatName.TEXT,
            subject="Subject",
            body="Body",
        )
        msg = rendered.build_message(
            to="user@example.com",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )
        assert msg.to == ["user@example.com"]
        assert msg.cc == ["cc@example.com"]
        assert msg.bcc == ["bcc@example.com"]
        assert msg.subject == "Subject"
        assert msg.body == "Body"

    def test_build_message_lists(self) -> None:
        rendered = RenderedEmail(
            format=EmailFormatName.TEXT,
            subject="Subject",
            body="Body",
        )
        msg = rendered.build_message(
            to=["to@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
        assert msg.to == ["to@example.com"]
        assert msg.cc == ["cc@example.com"]
        assert msg.bcc == ["bcc@example.com"]

    def test_invalid_format(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(EMAIL_FORMATS, clear=True)
        with pytest.raises(ValueError, match="Unregistered email format"):
            RenderedEmail(
                format=EmailFormatName.TEXT,
                subject="Subject",
                body="Body",
            )

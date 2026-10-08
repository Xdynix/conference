from pathlib import Path
from typing import Any

import pytest
from django.core.mail import EmailMultiAlternatives
from jinja2 import UndefinedError
from pydantic import HttpUrl
from pytest_mock import MockerFixture

from app.utils.email import (
    EMAIL_FORMATS,
    MAX_RENDERED_BODY_LENGTH,
    EmailContext,
    EmailFormatName,
    EmailRenderError,
    EmailTemplate,
    MarkdownFormat,
    RenderedBodyTooLongError,
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

    def test_render_html_is_none(self) -> None:
        assert TextFormat.render_html("Hello {{ name }}", {"name": "World"}) is None


class TestMarkdownFormat:
    def test_render_is_plain_text(self) -> None:
        assert (
            MarkdownFormat.render("Hi **{{ name }}**", {"name": "a*b"}) == "Hi **a*b**"
        )

    def test_render_html_happy_path(self) -> None:
        template = "Hi **{{ name }}**, you have {{ count }} items:\n\n- {{ title }}"
        context = {"name": "Ann", "count": 2, "title": "T"}
        html = MarkdownFormat.render_html(template, context)
        assert "<strong>Ann</strong>, you have 2 items:" in html
        assert "<li>T</li>" in html

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param("a *b* <i>c</i>", "a *b* &lt;i&gt;c&lt;/i&gt;", id="str"),
            pytest.param(
                ["a *b*", "<i>c</i>"],
                "['a *b*', '&lt;i&gt;c&lt;/i&gt;']",
                id="list",
            ),
            pytest.param(3, "3", id="int"),
        ],
    )
    def test_variable_is_escaped(self, value: object, expected: str) -> None:
        html = MarkdownFormat.render_html("{{ v }}", {"v": value})
        assert html == f"<p>{expected}</p>\n"

    def test_url_value_autolinks(self) -> None:
        context = {"url": HttpUrl("https://e.test/a_b")}
        html = MarkdownFormat.render_html("See {{ url }}", context)
        link = '<a href="https://e.test/a_b" rel="noopener noreferrer">'
        assert f"{link}https://e.test/a_b</a>" in html


class TestEmailContext:
    def test_context_validation(self) -> None:
        class MyContext(EmailContext):
            name: str

        MyContext.model_validate({"name": "test"})
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
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
        assert rendered.html is None
        assert rendered.format == EmailFormatName.TEXT

    def test_render_passes_body_to_render_html(self, mocker: MockerFixture) -> None:
        class MyContext(EmailContext):
            name: str

        spy = mocker.spy(MarkdownFormat, "render_html")
        template = EmailTemplate(
            format=EmailFormatName.MARKDOWN,
            subject="Hello {{ name }}",
            body="Dear **{{ name }}**",
        )
        rendered = template.render(MyContext(name="User"))
        spy.assert_called_once_with("Dear **{{ name }}**", {"name": "User"})
        assert rendered.html == spy.spy_return

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            pytest.param("{{ missing }}", "'missing' is undefined", id="undefined"),
            pytest.param("{{ ''.__class__ }}", "unsafe", id="sandbox_violation"),
            pytest.param("{{ range(10**6) }}", "Range too big", id="range_too_big"),
        ],
    )
    def test_render_wraps_template_errors(self, body: str, message: str) -> None:
        template = EmailTemplate(subject="Subject", body=body)
        with pytest.raises(EmailRenderError, match=message):
            template.render(EmailContext())

    @pytest.mark.parametrize(
        ("length", "ok"),
        [
            pytest.param(MAX_RENDERED_BODY_LENGTH, True, id="at_limit"),
            pytest.param(MAX_RENDERED_BODY_LENGTH + 1, False, id="over_limit"),
        ],
    )
    def test_render_body_length_limit(self, length: int, ok: bool) -> None:
        template = EmailTemplate(subject="Subject", body=f"{{{{ 'a' * {length} }}}}")
        if ok:
            assert len(template.render(EmailContext()).body) == length
        else:
            with pytest.raises(RenderedBodyTooLongError):
                template.render(EmailContext())

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
            reply_to="reply@example.com",
            from_email="admin@example.com",
        )
        assert isinstance(msg, EmailMultiAlternatives)
        assert msg.to == ["user@example.com"]
        assert msg.cc == ["cc@example.com"]
        assert msg.bcc == ["bcc@example.com"]
        assert msg.reply_to == ["reply@example.com"]
        assert msg.from_email == "admin@example.com"
        assert msg.subject == "Subject"
        assert msg.body == "Body"
        assert msg.content_subtype == "plain"
        assert msg.alternatives == []

    def test_build_message_html_alternative(self) -> None:
        rendered = RenderedEmail(
            format=EmailFormatName.MARKDOWN,
            subject="Subject",
            body="**Body**",
            html="<p><strong>Body</strong></p>",
        )
        msg = rendered.build_message(to="user@example.com")
        assert msg.body == "**Body**"
        assert msg.alternatives == [("<p><strong>Body</strong></p>", "text/html")]

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
            reply_to=["reply@example.com"],
        )
        assert msg.to == ["to@example.com"]
        assert msg.cc == ["cc@example.com"]
        assert msg.bcc == ["bcc@example.com"]
        assert msg.reply_to == ["reply@example.com"]

    def test_invalid_format(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(EMAIL_FORMATS, clear=True)
        with pytest.raises(ValueError, match="Unregistered email format"):
            RenderedEmail(
                format=EmailFormatName.TEXT,
                subject="Subject",
                body="Body",
            )

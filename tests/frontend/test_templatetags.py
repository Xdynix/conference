from collections.abc import Callable
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.template import Context, Template


@pytest.fixture
def make_md_file(tmp_path: Path, settings: LazySettings) -> Callable[[str, str], str]:
    settings.BASE_DIR = tmp_path

    def make_md_file(name: str, content: str) -> str:
        (tmp_path / name).write_text(content)
        return name

    return make_md_file


def render_tag(path: str) -> str:
    template = Template(
        '{% load frontend_tags %}{% render_markdown_file "' + path + '" %}'
    )
    return template.render(Context())


class TestRenderMarkdownFile:
    def test_renders_markdown_to_html(
        self,
        make_md_file: Callable[[str, str], str],
    ) -> None:
        path = make_md_file("basic.md", "**bold** and *italic*")

        result = render_tag(path)

        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result
        assert "&lt;strong&gt;" not in result

    def test_skips_sanitization(self, make_md_file: Callable[[str, str], str]) -> None:
        path = make_md_file("trusted.md", "<script>alert(1)</script>")

        result = render_tag(path)

        assert "<script>" in result

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            render_tag("missing.md")

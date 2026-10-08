import html
import string
from textwrap import dedent

import pytest

from app.utils.markdown import escape, render

SAMPLE_VALUE = f"{string.punctuation} x_y *z* <b>q</b> [l](http://e.test) 1. two # h"


def html_literal(value: str) -> str:
    """Return the value as the sanitized renderer emits it when it is plain text."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TestRender:
    def test_basic_paragraph(self) -> None:
        result = render("Hello, world!")
        assert "<p>Hello, world!</p>" in result

    def test_headings(self) -> None:
        result = render("# Heading 1\n## Heading 2\n### Heading 3")
        assert "<h1>Heading 1</h1>" in result
        assert "<h2>Heading 2</h2>" in result
        assert "<h3>Heading 3</h3>" in result

    def test_emphasis(self) -> None:
        result = render("**bold** and *italic*")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_unordered_list(self) -> None:
        md = "- Item 1\n- Item 2\n- Item 3"
        result = render(md)
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result
        assert "<li>Item 2</li>" in result
        assert "<li>Item 3</li>" in result

    def test_ordered_list(self) -> None:
        md = "1. First\n2. Second\n3. Third"
        result = render(md)
        assert "<ol>" in result
        assert "<li>First</li>" in result

    def test_links(self) -> None:
        result = render("[Example](https://example.com)")
        assert '<a href="https://example.com"' in result
        assert "Example</a>" in result

    def test_code_inline(self) -> None:
        result = render("Use `render()` function")
        assert "<code>render()</code>" in result

    def test_code_block(self) -> None:
        md = "```python\nprint('hello')\n```"
        result = render(md)
        assert "<pre>" in result
        assert "<code" in result
        assert "print(&#x27;hello&#x27;)" in result or "print('hello')" in result

    def test_blockquote(self) -> None:
        result = render("> This is a quote")
        assert "<blockquote>" in result
        assert "This is a quote" in result


class TestGfmFeatures:
    def test_strikethrough(self) -> None:
        result = render("~~deleted~~")
        assert "<s>deleted</s>" in result or "<del>deleted</del>" in result

    def test_table(self) -> None:
        md = dedent("""
        | Header 1 | Header 2 |
        |----------|----------|
        | Cell 1   | Cell 2   |
        """)
        result = render(md)
        assert "<table>" in result
        assert "<th>Header 1</th>" in result
        assert "<td>Cell 1</td>" in result

    def test_autolink(self) -> None:
        result = render("Visit https://example.com for more info")
        assert '<a href="https://example.com"' in result

    def test_task_list(self) -> None:
        md = "- [ ] Todo\n- [x] Done"
        result = render(md)
        assert "Todo" in result
        assert "Done" in result


class TestSanitization:
    def test_script_tag_removed(self) -> None:
        md = "<script>alert('xss')</script>"
        result = render(md)
        assert "<script>" not in result
        assert "alert" not in result.lower() or "&lt;script&gt;" in result

    def test_onclick_handler_removed(self) -> None:
        md = '<a href="#" onclick="alert(1)">Click</a>'
        result = render(md)
        assert "onclick" not in result

    def test_javascript_url_removed(self) -> None:
        md = '<a href="javascript:alert(1)">Click</a>'
        result = render(md)
        assert "javascript:" not in result

    def test_onerror_handler_removed(self) -> None:
        md = '<img src="x" onerror="alert(1)">'
        result = render(md)
        assert "onerror" not in result

    def test_data_url_in_img(self) -> None:
        md = '<img src="data:text/html,<script>alert(1)</script>">'
        result = render(md)
        assert "<script>" not in result

    def test_style_attribute_removed(self) -> None:
        md = '<p style="background:url(javascript:alert(1))">text</p>'
        result = render(md)
        assert "style=" not in result or "javascript" not in result

    def test_safe_html_preserved(self) -> None:
        md = "<strong>bold</strong> and <em>italic</em>"
        result = render(md)
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_unsanitized_preserves_script_tag(self) -> None:
        md = "<script>alert('xss')</script>"
        result = render(md, sanitize=False)
        assert "<script>" in result

    def test_unsanitized_preserves_attributes(self) -> None:
        md = '<a href="#" class="btn" target="_blank">Click</a>'
        result = render(md, sanitize=False)
        assert 'class="btn"' in result
        assert 'target="_blank"' in result


class TestEdgeCases:
    def test_empty_string(self) -> None:
        result = render("")
        assert result == ""

    def test_whitespace_only(self) -> None:
        result = render("   \n\n   ")
        assert result.strip() == ""

    def test_special_characters(self) -> None:
        result = render("Special chars: <>&\"'")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_unicode(self) -> None:
        result = render("Unicode: 你好 🎉 émojis")
        assert "你好" in result
        assert "🎉" in result
        assert "émojis" in result

    def test_nested_formatting(self) -> None:
        result = render("***bold and italic***")
        assert "<strong>" in result or "<em>" in result


class TestComplexMarkdown:
    """Tests for complex, real-world Markdown content."""

    def test_file_instructions_example(self) -> None:
        md = dedent("""
        **File requirements:**

        - Maximum size: 50 MB
        - Formats: PDF, DOCX, ZIP

        Please follow the [conference template](https://example.com/template)
        before uploading.
        """)
        result = render(md)
        assert "<strong>File requirements:</strong>" in result
        assert "<ul>" in result
        assert "<li>Maximum size: 50 MB</li>" in result
        assert '<a href="https://example.com/template"' in result
        assert "conference template</a>" in result

    def test_multiline_code_block(self) -> None:
        md = dedent("""
        ```python
        def hello():
            print("Hello, world!")
        ```
        """)
        result = render(md)
        assert "<pre>" in result
        assert "def hello():" in result

    def test_mixed_content(self) -> None:
        md = dedent("""
        # Title

        Some **bold** and *italic* text.

        1. First item
        2. Second item

        > A quote

        `inline code` and a [link](https://example.com).
        """)
        result = render(md)
        assert "<h1>Title</h1>" in result
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result
        assert "<ol>" in result
        assert "<blockquote>" in result
        assert "<code>inline code</code>" in result
        assert '<a href="https://example.com"' in result


class TestEscape:
    def test_all_punctuation_renders_literally(self) -> None:
        rendered = render(escape(string.punctuation))
        inner = rendered.removeprefix("<p>").removesuffix("</p>\n")
        assert html.unescape(inner) == string.punctuation

    def test_non_punctuation_untouched(self) -> None:
        assert escape("Héllo wörld 123") == "Héllo wörld 123"

    @pytest.mark.parametrize(
        ("template", "expected"),
        [
            pytest.param("Dear {v}, hello", "<p>Dear {v}, hello</p>", id="inline"),
            pytest.param("{v}", "<p>{v}</p>", id="line_start"),
            pytest.param("**{v}**", "<strong>{v}</strong>", id="in_bold"),
            pytest.param(
                "[{v}](https://e.test/)",
                '<a href="https://e.test/" rel="noopener noreferrer">{v}</a>',
                id="in_link_text",
            ),
            pytest.param("- {v}", "<li>{v}</li>", id="in_list_item"),
            pytest.param("| h |\n|---|\n| {v} |", "<td>{v}</td>", id="in_table_cell"),
        ],
    )
    def test_value_renders_literally_in_position(
        self,
        template: str,
        expected: str,
    ) -> None:
        result = render(template.format(v=escape(SAMPLE_VALUE)))
        assert expected.format(v=html_literal(SAMPLE_VALUE)) in result

    @pytest.mark.parametrize(
        ("template", "value", "expected"),
        [
            pytest.param(
                "- {v}",
                "Vector<T> Operations in Modern C++",
                "<li>Vector&lt;T&gt; Operations in Modern C++</li>",
                id="generic_type_brackets",
            ),
            pytest.param(
                "**{v}**",
                "Rethinking __init__ and __call__ in Python",
                "<strong>Rethinking __init__ and __call__ in Python</strong>",
                id="dunder_names",
            ),
            pytest.param(
                "- {v}",
                "A *Really* Simple Baseline for Few-Shot Learning",
                "<li>A *Really* Simple Baseline for Few-Shot Learning</li>",
                id="asterisk_emphasis",
            ),
            pytest.param(
                "| h |\n|---|\n| {v} |",
                "Accuracy | Efficiency Tradeoffs",
                "<td>Accuracy | Efficiency Tradeoffs</td>",
                id="pipe_in_table_cell",
            ),
            pytest.param(
                "{v}",
                "Dept. of CS, [State University](https://phish.example/login)",
                "<p>Dept. of CS, [State University](https://phish.example/login)</p>",
                id="markdown_link",
            ),
            pytest.param(
                "{v}",
                'Deep Learning <img src="https://tracker.example/1.gif"> for Proteins',
                '<p>Deep Learning &lt;img src="https://tracker.example/1.gif"&gt;'
                " for Proteins</p>",
                id="img_tag",
            ),
            pytest.param(
                "{v}",
                "<script>alert(1)</script>",
                "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>",
                id="script_tag",
            ),
        ],
    )
    def test_syntax_like_value_renders_literally(
        self,
        template: str,
        value: str,
        expected: str,
    ) -> None:
        """Values modelled on user-entered free text."""
        assert expected in render(template.format(v=escape(value)))

    @pytest.mark.parametrize(
        ("template", "expected"),
        [
            pytest.param("`{v}`", "<code>a\\*b</code>", id="code_span"),
            pytest.param("<div>\n{v}\n</div>", "<div>\na\\*b\n</div>", id="html_block"),
        ],
    )
    def test_escapes_stay_literal_in_raw_contexts(
        self,
        template: str,
        expected: str,
    ) -> None:
        assert expected in render(template.format(v=escape("a*b")))

    def test_indented_value_becomes_code_block(self) -> None:
        assert "<pre><code>indented" in render(escape("    indented"))

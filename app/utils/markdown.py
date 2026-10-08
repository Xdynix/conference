__all__ = ("escape", "render")

import re
import string
from functools import lru_cache

import nh3
from markdown_it import MarkdownIt

md = MarkdownIt("gfm-like")

_PUNCTUATION = re.compile(f"[{re.escape(string.punctuation)}]")


def escape(content: str) -> str:
    """Backslash-escape ASCII punctuation so the content renders as literal text.

    CommonMark lets a backslash escape any ASCII punctuation character, which covers
    every inline and block construct. Escapes have no effect inside code spans, code
    blocks and HTML blocks, and whitespace-driven syntax such as indented code is not
    covered.
    """
    return _PUNCTUATION.sub(r"\\\g<0>", content)


@lru_cache
def render(content: str, *, sanitize: bool = True) -> str:
    """Render Markdown to HTML."""
    html = md.render(content)
    return nh3.clean(html) if sanitize else html

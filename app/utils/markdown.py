__all__ = ("render",)

from functools import lru_cache

import nh3
from markdown_it import MarkdownIt

md = MarkdownIt("gfm-like")


@lru_cache
def render(content: str) -> str:
    """Render Markdown to sanitized HTML."""
    return nh3.clean(md.render(content))

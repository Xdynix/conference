__all__ = ("render",)

from functools import lru_cache

import nh3
from markdown_it import MarkdownIt

md = MarkdownIt("gfm-like")


@lru_cache
def render(content: str, *, sanitize: bool = True) -> str:
    """Render Markdown to HTML."""
    html = md.render(content)
    return nh3.clean(html) if sanitize else html

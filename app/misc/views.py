from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


async def favicon(request: HttpRequest) -> HttpResponse:
    """Provides a simple text-based favicon as a fallback."""
    return render(
        request,
        "misc/favicon.svg",
        context={"favicon_text": settings.FAVICON_TEXT},
        content_type="image/svg+xml",
    )

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from app.utils.cf_turnstile.decorators import cf_turnstile_required

CF_TURNSTILE_ACTION = "demo"


@require_GET
async def demo(request: HttpRequest) -> HttpResponse:  # pragma: no cover
    """Render Turnstile demo page."""
    return render(
        request,
        "turnstile/demo.html",
        context={
            "csrf_header_name": (
                settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-")
            ),
            "cf_turnstile_site_key": settings.CF_TURNSTILE_SITE_KEY,
            "cf_turnstile_response_header_name": (
                settings.CF_TURNSTILE_RESPONSE_HEADER_NAME
            ),
            "cf_turnstile_action": CF_TURNSTILE_ACTION,
        },
    )


@require_POST
@cf_turnstile_required
async def demo_api(_: HttpRequest) -> HttpResponse:  # pragma: no cover
    """Verify Cloudflare Turnstile response."""
    return JsonResponse({"message": "Success!"})

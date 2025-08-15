from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_text_html
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def password_reset_page(request: HttpRequest) -> HttpResponse:  # pragma: no cover
    """Provide a minimum password reset page.

    This view is mainly for development purposes.
    """
    return render(
        request,
        "core/password-reset-page.html",
        context={
            "csrf_header_name": (
                settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-")
            ),
            "cf_turnstile_site_key": settings.CF_TURNSTILE_SITE_KEY,
            "cf_turnstile_response_header_name": (
                settings.CF_TURNSTILE_RESPONSE_HEADER_NAME
            ),
            "password_validators_help_text_html": password_validators_help_text_html(),
        },
    )

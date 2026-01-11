from typing import Any

from django.conf import settings

from app.utils.cf_turnstile.types import CFTurnstileMode


def config(_: Any) -> dict[str, Any]:
    turnstile_enabled = settings.CF_TURNSTILE_MODE != CFTurnstileMode.DISABLED and bool(
        settings.CF_TURNSTILE_SITE_KEY
    )
    return {
        "settings": {
            "SITE_NAME": settings.SITE_NAME,
            "BRANDING": {
                "logo_url": settings.BRANDING_LOGO_URL,
                "logo_alt": settings.BRANDING_LOGO_ALT,
                "logo_height": settings.BRANDING_LOGO_HEIGHT,
                "parent_url": settings.BRANDING_PARENT_URL,
                "favicon_url": settings.BRANDING_FAVICON_URL,
            },
            "CSRF_HEADER_NAME": (
                settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-")
            ),
            "CF_TURNSTILE": {
                "enabled": turnstile_enabled,
                "site_key": settings.CF_TURNSTILE_SITE_KEY,
                "response_header_name": settings.CF_TURNSTILE_RESPONSE_HEADER_NAME,
            },
        },
    }

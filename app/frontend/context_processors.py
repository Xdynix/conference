from typing import Any

from django.conf import settings

from app.utils.cf_turnstile.types import CFTurnstileMode


def cf_turnstile(_: Any) -> dict[str, Any]:
    """Provide Cloudflare Turnstile configuration to templates."""
    enabled = settings.CF_TURNSTILE_MODE != CFTurnstileMode.DISABLED and bool(
        settings.CF_TURNSTILE_SITE_KEY
    )
    return {
        "cf_turnstile": {
            "enabled": enabled,
            "site_key": settings.CF_TURNSTILE_SITE_KEY,
            "response_header_name": settings.CF_TURNSTILE_RESPONSE_HEADER_NAME,
        },
    }

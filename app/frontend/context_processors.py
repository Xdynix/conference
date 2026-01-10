from typing import Any

from django.conf import settings


def config(_: Any) -> dict[str, Any]:
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
        },
    }

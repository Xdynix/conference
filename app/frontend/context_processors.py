from typing import Any

from django.conf import settings


def config(_: Any) -> dict[str, Any]:
    return {
        "settings": {
            "SITE_NAME": settings.SITE_NAME,
        },
    }

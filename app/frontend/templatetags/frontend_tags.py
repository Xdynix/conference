import json
from typing import Any

from django import template
from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts

from app.frontend.views import ProtectedView
from app.utils.enums import Region

register = template.Library()

# Valid ULID placeholders for URL templates. These are syntactically valid ULIDs with
# near-zero timestamps that will never occur naturally. Must match ULID_PLACEHOLDERS in
# utils.js.
_ULID_PLACEHOLDERS = (
    "00000000000000000000000001",
    "00000000000000000000000002",
    "00000000000000000000000003",
)


@register.simple_tag
def ulid_placeholder(index: int) -> str:
    """Return a ULID placeholder for URL templates. Index is 1-based."""
    return _ULID_PLACEHOLDERS[index - 1]


@register.simple_tag
def regions_json() -> str:
    regions = [[r.name, r.value] for r in Region]
    return json.dumps(regions)


@register.simple_tag
def password_help_texts() -> list[str]:
    return password_validators_help_texts()


@register.simple_tag
def site_name() -> str:
    return settings.SITE_NAME


@register.simple_tag
def branding() -> dict[str, Any]:
    return {
        "logo_url": settings.BRANDING_LOGO_URL,
        "logo_alt": settings.BRANDING_LOGO_ALT,
        "logo_height": settings.BRANDING_LOGO_HEIGHT,
        "parent_url": settings.BRANDING_PARENT_URL,
        "favicon_url": settings.BRANDING_FAVICON_URL,
    }


@register.simple_tag
def csrf_header_name() -> str:
    return settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-")


@register.simple_tag
def redirect_field_name() -> Any:
    return ProtectedView.redirect_field_name

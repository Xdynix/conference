import json
from collections.abc import Iterable
from enum import Enum
from typing import Any

from django import template
from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts
from django.utils.safestring import SafeString, mark_safe

from app.frontend.views import ProtectedView
from app.utils.enums import Region

register = template.Library()


def _enum_to_dict(
    enum_class: type[Enum],
    collections: Iterable[str] = (),
) -> dict[str, Any]:
    """Convert an enum to a dict with value and label for each member.

    Works with both StrEnum (value used as label) and TextChoices (has .label).
    Optionally includes collections (class methods that return sequences of members).
    """
    result: dict[str, Any] = {}
    for member in enum_class:
        label = getattr(member, "label", member.value)
        result[member.name] = {"value": member.value, "label": str(label)}
    result["_collections"] = {
        name: [m.value for m in getattr(enum_class, name)()] for name in collections
    }
    return result


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
def regions_json() -> SafeString:
    """Return regions as JSON for use in script tags."""
    regions = [[r.name, r.value] for r in Region]
    return mark_safe(json.dumps(regions))  # noqa: S308


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


@register.simple_tag
def enums_json() -> SafeString:
    """Export enums to frontend as JSON with value and label for each member."""
    from app.conference.models import (
        ConferenceRole,
        ConferenceVisibility,
        Invitation,
        PaperState,
        TrackRole,
        TrackVisibility,
    )
    from app.core.models import GlobalRole

    return mark_safe(  # noqa: S308
        json.dumps(
            {
                "ConferenceRole": _enum_to_dict(
                    ConferenceRole,
                    collections=["admins", "reviewers"],
                ),
                "ConferenceVisibility": _enum_to_dict(ConferenceVisibility),
                "GlobalRole": _enum_to_dict(GlobalRole),
                "InvitationState": _enum_to_dict(Invitation.State),
                "PaperState": _enum_to_dict(PaperState),
                "TrackRole": _enum_to_dict(
                    TrackRole,
                    collections=["admins", "reviewers"],
                ),
                "TrackVisibility": _enum_to_dict(TrackVisibility),
            }
        )
    )

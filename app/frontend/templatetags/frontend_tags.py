import json

from django import template
from django.contrib.auth.password_validation import password_validators_help_texts

from app.utils.enums import Region

register = template.Library()


@register.simple_tag
def regions_json() -> str:
    """Output regions as JSON array of [code, name] pairs."""
    regions = [[r.name, r.value] for r in Region]
    return json.dumps(regions)


@register.simple_tag
def password_help_texts() -> list[str]:
    """Output password validator help texts."""
    return password_validators_help_texts()

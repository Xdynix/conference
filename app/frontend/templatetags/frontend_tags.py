import json

from django import template

from app.utils.enums import Region

register = template.Library()


@register.simple_tag
def regions_json() -> str:
    """Output regions as JSON array of [code, name] pairs."""
    regions = [[r.name, r.value] for r in Region]
    return json.dumps(regions)

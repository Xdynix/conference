from typing import Annotated, Any

from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.cache import never_cache
from ipware import get_client_ip
from ninja import Router, Schema
from ninja.decorators import decorate_view
from pydantic import AwareDatetime, Field

router = Router(tags=["Misc"], exclude_none=True)


class HealthStatus(Schema):
    now: AwareDatetime
    client_ip: Annotated[str, Field(examples=["192.168.1.1", "2001:db8::1"])] | None


@router.get("/health-status", auth=None, response=HealthStatus, summary="Ping")
@decorate_view(never_cache)
async def get_health_status(request: HttpRequest) -> dict[str, Any]:
    """Return server status and client connection information."""
    now = timezone.now()
    client_ip, _ = get_client_ip(request)
    return {
        "now": now,
        "client_ip": client_ip,
    }

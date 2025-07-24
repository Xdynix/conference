from typing import Any

from django.utils import timezone
from django.views.decorators.cache import never_cache
from ninja import Router, Schema
from ninja.decorators import decorate_view
from pydantic import AwareDatetime

router = Router(tags=["Misc"])


class HealthStatus(Schema):
    now: AwareDatetime


@router.get("/health-status", auth=None, response=HealthStatus, summary="Ping")
@decorate_view(never_cache)
async def get_health_status(*_: Any) -> dict[str, Any]:
    """Simply return current time.

    Can be used to check that the server is online and can communicate in real time.
    """
    return {"now": timezone.now()}

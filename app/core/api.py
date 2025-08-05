from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Router
from ninja.decorators import decorate_view

from app.core.schemas import Session
from app.core.types import HttpRequest

router = Router(tags=["Core"], exclude_none=True)


@router.get(
    "/sessions/current",
    response=Session,
    summary="Get Session",
)
@decorate_view(ensure_csrf_cookie, never_cache)
async def get_session(request: HttpRequest) -> Session:
    """Get the session details. Includes the authenticated user, if any."""
    return await Session.from_request(request)

from http import HTTPStatus

from django.contrib.auth import aauthenticate, alogin
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from loguru import logger
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from app.core.schemas import Session
from app.core.types import HttpRequest, Password, Username
from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required

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


class CreateSessionRequest(Schema):
    username: Username
    password: Password


@router.post(
    "/sessions",
    response={
        HTTPStatus.OK: Session,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Login",
)
@decorate_view(cf_turnstile_required)
async def create_session(
    request: HttpRequest,
    payload: CreateSessionRequest,
) -> Session:
    """Log a user in."""
    user = await aauthenticate(
        request,
        username=payload.username,
        password=payload.password.get_secret_value(),
    )
    if user is None:
        logger.info("Failed login attempt.", username=payload.username)
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Invalid credentials."),
        )
    logger.info("User logged in.", user=user)
    await alogin(request, user)
    return await Session.from_request(request)

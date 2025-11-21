from http import HTTPStatus
from typing import Literal, Self

from django.contrib.auth import aauthenticate, alogin, alogout
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from loguru import logger
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from app.core.auth import is_superuser
from app.core.models import User
from app.core.registry.user_response import user_response_registry
from app.core.types import HttpRequest, Password, Username
from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.throttling import AnonThrottle, throttling

router = Router(tags=["Session"], exclude_none=True)

UserResponse = user_response_registry.get_schema()


class Session(Schema):
    class Key:
        IMPERSONATOR_ID = "impersonator_id"

    user: UserResponse | None  # type: ignore[valid-type]
    impersonating: Literal[True] | None

    @classmethod
    async def from_request(cls, request: HttpRequest) -> Self:
        user = await request.auser()
        if user.is_authenticated:
            user_data = await user_response_registry.dump(user)
        else:
            user_data = None
        return cls.model_validate(
            {
                "user": user_data,
                "impersonating": (cls.Key.IMPERSONATOR_ID in request.session) or None,
            }
        )


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
@decorate_view(throttling(AnonThrottle("100/min")))
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
    await alogin(request, user)

    logger.info("User logged in.", user=user)

    return await Session.from_request(request)


@router.delete(
    "/sessions/current",
    response=Session,
    summary="Logout",
)
async def delete_session(request: HttpRequest) -> Session:
    """Log a user out."""
    if (user := await request.auser()).is_authenticated:
        await alogout(request)

        logger.info("User logged out.", user=user)

    return await Session.from_request(request)


class AssumeSessionRequest(Schema):
    impersonated: Username


@router.post(
    "/sessions/current:assume",
    response={
        HTTPStatus.OK: Session,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Start Impersonation",
    auth=is_superuser,
)
async def assume_session(
    request: HttpRequest,
    payload: AssumeSessionRequest,
) -> Session:
    """Impersonate a user as another user.

    This backdoor operation allows a superuser to authenticate as another user without
    knowing their credentials. This can be used to investigate issues from their
    perspective to better support and assist them.

    - Only superusers can use this operation.
    - The user being impersonated cannot be a superuser.
    """
    impersonated: User | None = (
        await User.objects.active().filter(username=payload.impersonated).afirst()
    )
    if impersonated is None:
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Impersonated not found."),
        )
    if impersonated.is_superuser:
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Cannot impersonate a superuser."),
        )

    impersonator = await request.auser()
    await alogin(request, impersonated)
    request.session[Session.Key.IMPERSONATOR_ID] = str(impersonator.id)

    logger.info(
        "Impersonation started.",
        impersonator=impersonator,
        impersonated=impersonated,
    )

    return await Session.from_request(request)


@router.post(
    "/sessions/current:revert",
    response=Session,
    summary="Stop Impersonation",
)
async def revert_session(request: HttpRequest) -> Session:
    """Revert the current session to the state before impersonating.

    - If the current session is not impersonated, there will be no change.
    - If the impersonator is no longer active, the current session will be logged out.
    """
    impersonator_id: str | None = await request.session.aget(
        Session.Key.IMPERSONATOR_ID
    )
    if impersonator_id is None:
        return await Session.from_request(request)

    impersonator = await User.objects.active().filter(id=impersonator_id).afirst()
    if impersonator is not None:
        impersonated = await request.auser()
        await alogin(request, impersonator)

        logger.info(
            "Impersonation stopped.",
            impersonator=impersonator,
            impersonated=impersonated,
        )
    else:
        await alogout(request)

        logger.error(
            "Impersonator not found.",
            impersonator_id=impersonator_id,
        )

    return await Session.from_request(request)

from http import HTTPStatus
from typing import Annotated, Literal, Self, cast

from asgiref.sync import sync_to_async
from django.contrib.auth import aauthenticate, alogin, alogout
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from loguru import logger
from ninja import Field, Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from pydantic import SecretStr, StringConstraints

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.core.auth import is_superuser
from app.core.models import ApiKeySession, User
from app.core.registry.user_response import user_response_registry
from app.core.services.api_key import ApiKeyService
from app.core.types import AuthedHttpRequest, HttpRequest, Password, Username
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
    username: Annotated[
        str,
        StringConstraints(max_length=254, strip_whitespace=True),
        Field(description=_("Username or email address.")),
    ]
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
    """Log a user in. Accepts either a username or email address."""
    user = await aauthenticate(
        request,
        username=payload.username,
        password=payload.password.get_secret_value(),
    )
    if user is None:
        await audit(
            request=request,
            action=AuditAction.SESSION_CREATE_FAILED,
            resource=AuditResource.SESSION,
            payload=payload,
        )
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Invalid credentials."),
        )
    await alogin(request, user)

    await audit(
        request=request,
        action=AuditAction.SESSION_CREATE,
        resource=AuditResource.SESSION,
        resource_id=str(user.uid),
        payload=payload,
    )

    return await Session.from_request(request)


class CreateApiKeySessionRequest(Schema):
    key: SecretStr


@router.post(
    "/sessions/api-key",
    response={
        HTTPStatus.OK: Session,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="API Key Login",
)
@decorate_view(ensure_csrf_cookie)
@decorate_view(throttling(AnonThrottle("100/min")))
async def create_api_key_session(
    request: HttpRequest,
    payload: CreateApiKeySessionRequest,
) -> Session:
    """Create a session using an API key.

    Authenticates via API key instead of username/password, bypassing Turnstile. Scripts
    should persist the returned session and CSRF cookies for subsequent requests.
    """
    api_key = await sync_to_async(ApiKeyService.authenticate_key)(
        payload.key.get_secret_value()
    )
    if api_key is None:
        await audit(
            request=request,
            action=AuditAction.SESSION_CREATE_API_KEY_FAILED,
            resource=AuditResource.SESSION,
            payload=payload,
        )
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Invalid credentials."),
        )

    try:
        await sync_to_async(ApiKeyService.api_key_login)(request, api_key)
    except ValueError as exc:  # pragma: no cover
        await audit(
            request=request,
            action=AuditAction.SESSION_CREATE_API_KEY_FAILED,
            resource=AuditResource.SESSION,
            payload=payload,
        )
        raise HttpError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            message=_("Invalid credentials."),
        ) from exc

    await audit(
        request=request,
        action=AuditAction.SESSION_CREATE_API_KEY,
        resource=AuditResource.SESSION,
        resource_id=str(api_key.user.uid),
        payload=payload,
    )

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

        await audit(
            request=request,
            action=AuditAction.SESSION_DELETE,
            resource=AuditResource.SESSION,
            actor=user,
        )

    return await Session.from_request(request)


class AssumeSessionRequest(Schema):
    impersonated: Username


@router.post(
    "/sessions/current:assume",
    response={
        HTTPStatus.OK: Session,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Start Impersonation",
    auth=is_superuser,
)
async def assume_session(
    request: AuthedHttpRequest,
    payload: AssumeSessionRequest,
) -> Session:
    """Impersonate a user as another user.

    This backdoor operation allows a superuser to authenticate as another user without
    knowing their credentials. This can be used to investigate issues from their
    perspective to better support and assist them.

    - Only superusers can use this operation.
    - The user being impersonated cannot be a superuser.
    - API key sessions cannot use impersonation.
    """
    if await ApiKeySession.objects.filter(
        session_id=request.session.session_key
    ).aexists():
        raise HttpError(
            status_code=HTTPStatus.BAD_REQUEST,
            message=_("API key sessions cannot use impersonation."),
        )

    impersonated = await aget_object_or_404(
        User.objects.active(),
        username=payload.impersonated,
    )

    # Prevent superusers from impersonating other superusers. This security policy
    # prevents privilege escalation chains, limits blast radius if a superuser account
    # is compromised, and avoids chained impersonation scenarios. Superusers already
    # have full system access without needing impersonation.
    if impersonated.is_superuser:
        raise HttpError(
            status_code=HTTPStatus.BAD_REQUEST,
            message=_("Cannot impersonate a superuser."),
        )

    impersonator = await request.auser()
    await alogin(request, impersonated)
    request.session[Session.Key.IMPERSONATOR_ID] = str(impersonator.id)

    await audit(
        request=request,
        action=AuditAction.SESSION_ASSUME,
        resource=AuditResource.SESSION,
        resource_id=str(impersonated.uid),
        actor=impersonator,
        payload=payload,
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
        impersonated = cast(User, await request.auser())
        await alogin(request, impersonator)

        await audit(
            request=request,
            action=AuditAction.SESSION_REVERT,
            resource=AuditResource.SESSION,
            actor=impersonator,
            detail={"impersonated_uid": str(impersonated.uid)},
        )
    else:
        await alogout(request)

        logger.error("Impersonator not found.", impersonator_id=impersonator_id)
        await audit(
            request=request,
            action=AuditAction.SESSION_REVERT,
            resource=AuditResource.SESSION,
            detail={"impersonator_id": impersonator_id},
        )

    return await Session.from_request(request)

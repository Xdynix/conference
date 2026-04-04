from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from asgiref.sync import iscoroutinefunction, sync_to_async
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import sync_and_async_middleware

from app.core.models import ApiKey, User
from app.core.services.api_key import ApiKeyService
from app.core.types import HttpRequest

_BEARER_PREFIX = f"Bearer {ApiKey.KEY_PREFIX}"
_KEY_PREFIX_LEN = len(ApiKey.KEY_PREFIX)


def _redact_key(token: str) -> str:
    """Produce a human-readable redacted form like ``cfk_hiQ...rO4``."""
    suffix = token[_KEY_PREFIX_LEN:]
    if len(suffix) <= 6:  # pragma: no cover
        return f"{ApiKey.KEY_PREFIX}***"
    return f"{ApiKey.KEY_PREFIX}{suffix[:3]}...{suffix[-3:]}"


def _extract_bearer_token(request: HttpRequest) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith(_BEARER_PREFIX):
        return auth[len("Bearer ") :]
    return None


def _invalid_credentials_response() -> JsonResponse:
    response = JsonResponse(
        {"message": "Invalid credentials."},
        status=HTTPStatus.UNAUTHORIZED,
    )
    response["WWW-Authenticate"] = "Bearer"
    return response


@sync_and_async_middleware
def api_key_auth_middleware[F: Callable[..., Any]](get_response: F) -> F:
    """Authenticate requests carrying ``Authorization: Bearer cfk_...``.

    Must be placed after ``AuthenticationMiddleware`` in the middleware stack. Sets
    ``request.api_key`` on every request (to the authenticated key or ``None``).

    This middleware is site-wide: it authenticates bearer tokens on all routes, not just
    Ninja API endpoints. Non-API routes (e.g., the admin site) still enforce their own
    authorization checks (``is_staff``, ``is_superuser``). CSRF enforcement is skipped
    for bearer-authenticated requests because they are not browser-initiated.
    """

    if iscoroutinefunction(get_response):

        async def middleware(request: HttpRequest) -> HttpResponse:
            token = _extract_bearer_token(request)
            if token is None:
                request.api_key = None
                request.api_key_label = ""
                return await get_response(request)  # type: ignore[no-any-return]

            api_key = await sync_to_async(ApiKeyService.authenticate_key)(token)
            if api_key is None:
                return _invalid_credentials_response()

            user = api_key.user
            request.user = user

            async def auser() -> User:
                return user

            request.auser = auser  # type: ignore[method-assign]
            request.api_key = api_key
            request.api_key_label = _redact_key(token)
            request._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

            await sync_to_async(ApiKeyService.touch_last_use)(api_key)

            return await get_response(request)  # type: ignore[no-any-return]

    else:

        def middleware(request: HttpRequest) -> HttpResponse:  # type: ignore[misc]
            token = _extract_bearer_token(request)
            if token is None:
                request.api_key = None
                request.api_key_label = ""
                return get_response(request)  # type: ignore[no-any-return]

            api_key = ApiKeyService.authenticate_key(token)
            if api_key is None:
                return _invalid_credentials_response()

            user = api_key.user
            request.user = user

            async def auser() -> User:
                return user

            request.auser = auser  # type: ignore[method-assign]
            request.api_key = api_key
            request.api_key_label = _redact_key(token)
            request._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

            ApiKeyService.touch_last_use(api_key)

            return get_response(request)  # type: ignore[no-any-return]

    return middleware  # type: ignore[return-value]

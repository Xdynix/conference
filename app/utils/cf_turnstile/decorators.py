__all__ = ("cf_turnstile_required",)

from collections.abc import Callable
from functools import partial, wraps
from http import HTTPStatus
from typing import Any, overload
from uuid import uuid4

import httpx
from asgiref.sync import async_to_sync, iscoroutinefunction
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _
from loguru import logger

from app.utils.cf_turnstile.types import CFTurnstileMode
from app.utils.cf_turnstile.verify import verify_cf_turnstile_response


async def check_cf_turnstile_response(
    request: HttpRequest,
    enforce_on_safe: bool = False,
) -> HttpResponse | None:
    """Check and verify a Cloudflare Turnstile response from an HTTP request.

    Args:
        request: The Django HTTP request object.
        enforce_on_safe: Whether to enforce Cloudflare Turnstile verification on safe
            HTTP methods (GET, HEAD, OPTIONS, TRACE). Defaults to ``False``.

    Returns:
        ``None`` if verification passes or should be skipped, otherwise returns an
        ``HttpResponse`` with appropriate error status and message.
    """
    if settings.CF_TURNSTILE_MODE == CFTurnstileMode.DISABLED:
        logger.debug("CF Turnstile verification disabled; bypassing check.")
        return None

    if not enforce_on_safe and request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return None

    if settings.DEBUG and not (
        settings.CF_TURNSTILE_SITE_KEY and settings.CF_TURNSTILE_SECRET_KEY
    ):  # pragma: no cover
        logger.warning("CF Turnstile not fully configured, skipping verification.")
        return None

    user = await request.auser()
    if user.is_superuser:
        logger.debug("Bypassed CF Turnstile verification for superuser.")
        return None

    header_name = settings.CF_TURNSTILE_RESPONSE_HEADER_NAME
    cf_turnstile_response = (
        request.headers.get(header_name) or request.POST.get(header_name) or ""
    )
    if not cf_turnstile_response:
        return JsonResponse(
            {
                "message": _("Missing {header_name} header.").format(
                    header_name=header_name,
                ),
            },
            status=HTTPStatus.FORBIDDEN,
        )

    bypass_secrets = settings.CF_TURNSTILE_BYPASS_SECRETS
    if cf_turnstile_response in bypass_secrets:
        logger.info("Bypassed CF Turnstile verification with secrets.")
        return None

    remote_ip: str | None = getattr(request, "client_ip", None)

    idempotency_key = uuid4()
    try:
        success, _detail = await verify_cf_turnstile_response(
            cf_turnstile_response,
            remote_ip=remote_ip,
            idempotency_key=idempotency_key,
        )
    except (httpx.HTTPStatusError, httpx.RequestError):
        logger.exception("Error verifying CF Turnstile response.")
        return JsonResponse(
            {"message": _("CF Turnstile unavailable.")},
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            headers={"Retry-After": "30"},
        )

    if not success:
        return JsonResponse(
            {
                "message": _("Invalid {header_name} header.").format(
                    header_name=header_name,
                ),
            },
            status=HTTPStatus.FORBIDDEN,
        )

    # TODO: Enforce `action` validation.

    return None


@overload
def cf_turnstile_required[F: Callable[..., Any]](
    view_func: F,
    /,
    *,
    enforce_on_safe: bool = False,
) -> F: ...


@overload
def cf_turnstile_required[F: Callable[..., Any]](
    view_func: None = None,
    /,
    *,
    enforce_on_safe: bool = False,
) -> Callable[[F], F]: ...


def cf_turnstile_required[F: Callable[..., Any]](
    view_func: F | None = None,
    /,
    *,
    enforce_on_safe: bool = False,
) -> F | Callable[[F], F]:
    """Decorator to require Cloudflare Turnstile verification for Django views.

    This decorator intercepts requests and validates Cloudflare Turnstile responses
    before allowing access to the protected view. Verification can be bypassed by:

    - **Disabled Mode**: Set ``CF_TURNSTILE_MODE=disabled`` to skip verification.
    - **Superuser Accounts**: Users with ``is_superuser=True`` automatically bypass
      verification.
    - **Bypass Secrets**: Providing a secret value configured in
      ``CF_TURNSTILE_BYPASS_SECRETS``.
    - **Development Environment**: Set ``DEBUG=True`` and leave
      ``CF_TURNSTILE_SECRET_KEY`` empty.

    Args:
        view_func: The view function to decorate (when used without parentheses).
        enforce_on_safe: Whether to enforce Turnstile verification on safe HTTP methods
            (GET, HEAD, OPTIONS, TRACE). Defaults to ``False``, meaning safe methods are
            allowed without verification.

    Returns:
        The decorated view function that performs Cloudflare Turnstile verification
        before calling the original view.

    Error Response Conditions:
        - 403 Forbidden: Missing or invalid Cloudflare Turnstile response.
        - 503 Service Unavailable: Cloudflare Turnstile API is unreachable or errors.

    Usage::

        # Basic usage (skips verification on safe methods):
        @cf_turnstile_required
        def my_view(request): ...

        # Force verification on all methods including GET:
        @cf_turnstile_required(enforce_on_safe=True)
        def protected_view(request): ...
    """
    if view_func is None:
        return partial(cf_turnstile_required, enforce_on_safe=enforce_on_safe)

    if iscoroutinefunction(view_func):

        @wraps(view_func)
        async def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            response = await check_cf_turnstile_response(
                request,
                enforce_on_safe=enforce_on_safe,
            )
            if response is not None:
                return response
            return await view_func(request, *args, **kwargs)

    else:
        sync_check_cf_turnstile_response = async_to_sync(check_cf_turnstile_response)

        @wraps(view_func)
        def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            response = sync_check_cf_turnstile_response(
                request,
                enforce_on_safe=enforce_on_safe,
            )
            if response is not None:
                return response
            return view_func(request, *args, **kwargs)

    return wrapped

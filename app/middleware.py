import string
import uuid
from collections.abc import Callable
from typing import Any

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpRequest as DjangoHttpRequest
from django.http import HttpResponse
from django.utils.decorators import sync_and_async_middleware
from ipware import get_client_ip
from loguru import logger

try:
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore[assignment]

_REQUEST_ID_MAX_LENGTH = 64
_REQUEST_ID_ALLOWED = frozenset(string.ascii_letters + string.digits + "-")


class HttpRequest(DjangoHttpRequest):
    """Type stub declaring middleware-attached request metadata."""

    request_id: str
    client_ip: str | None


def enrich_request(request: HttpRequest) -> None:
    """Attach client IP and request ID to the request object."""
    request.request_id = _resolve_request_id(request)
    request.client_ip = _resolve_client_ip(request)

    if sentry_sdk is not None:  # pragma: no branch
        sentry_sdk.set_tag("request_id", request.request_id)


def _meta_key(header: str) -> str:
    return f"HTTP_{header.upper().replace('-', '_')}"


def _resolve_request_id(request: HttpRequest) -> str:
    header = settings.REVERSE_PROXY_REQUEST_ID_HEADER
    if settings.TRUSTED_PROXY and header:
        value: str = request.META.get(_meta_key(header), "")
        sanitized = "".join(
            c for c in value[:_REQUEST_ID_MAX_LENGTH] if c in _REQUEST_ID_ALLOWED
        )
        if sanitized:
            return sanitized

    return uuid.uuid4().hex


def _resolve_client_ip(request: HttpRequest) -> str | None:
    if settings.TRUSTED_PROXY:
        # Never left to ipware's default order, which trusts headers a client can set.
        headers = settings.REVERSE_PROXY_IP_HEADERS or ["X-Forwarded-For"]
        ip, _ = get_client_ip(
            request,
            proxy_count=settings.REVERSE_PROXY_COUNT,
            request_header_order=[_meta_key(header) for header in headers],
        )
        if ip is not None:
            return ip

    ip, _ = get_client_ip(request, request_header_order=("REMOTE_ADDR",))
    return ip


@sync_and_async_middleware
def request_meta_middleware[F: Callable[..., Any]](get_response: F) -> F:
    """Attach request metadata (client IP, request ID) to every request."""

    if iscoroutinefunction(get_response):

        async def middleware(request: HttpRequest) -> HttpResponse:
            enrich_request(request)
            with logger.contextualize(
                request_id=request.request_id,
                client_ip=request.client_ip,
            ):
                return await get_response(request)  # type: ignore[no-any-return]

    else:

        def middleware(request: HttpRequest) -> HttpResponse:  # type: ignore[misc]
            enrich_request(request)
            with logger.contextualize(
                request_id=request.request_id,
                client_ip=request.client_ip,
            ):
                return get_response(request)  # type: ignore[no-any-return]

    return middleware  # type: ignore[return-value]

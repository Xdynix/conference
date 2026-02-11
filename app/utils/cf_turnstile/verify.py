__all__ = ("verify_cf_turnstile_response",)

from typing import Any
from uuid import UUID

import httpx
from django.conf import settings


async def verify_cf_turnstile_response(
    cf_turnstile_response: str,
    /,
    *,
    remote_ip: str | None = None,
    idempotency_key: UUID | None = None,
    secret_key: str = "",
    verify_url: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Verify a Cloudflare Turnstile response with the Turnstile API.

    Args:
        cf_turnstile_response: The Cloudflare Turnstile response from the client-side
            widget.
        remote_ip: The user's IP address for additional verification.
        idempotency_key: Optional UUID to prevent duplicate verifications.
        secret_key: The Cloudflare Turnstile secret key for API authentication.
        verify_url: The Cloudflare Turnstile verification endpoint URL.

    Returns:
        A tuple containing:
            - bool: Whether the response verification was successful.
            - dict: The complete API response data including error codes and metadata.

    Raises:
        httpx.HTTPStatusError: When the API returns a non-2xx HTTP status code.
        httpx.RequestError: For network-related errors (timeouts, connection failures,
            etc.).
    """
    secret_key = secret_key or settings.CF_TURNSTILE_SECRET_KEY
    verify_url = verify_url or settings.CF_TURNSTILE_VERIFY_URL

    payload = {
        "secret": secret_key,
        "response": cf_turnstile_response,
    }
    if remote_ip is not None:
        payload["remoteip"] = remote_ip
    if idempotency_key is not None:
        payload["idempotency_key"] = str(idempotency_key)

    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(retries=2),
        timeout=3,
    ) as client:
        # TODO: Retry 5xx and 429 if idempotency key is set.
        response = await client.post(verify_url, json=payload)
    response.raise_for_status()
    result = response.json()
    is_success = result.get("success", False)
    return is_success, result

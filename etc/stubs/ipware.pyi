from collections.abc import Iterable
from typing import Literal

from django.http import HttpRequest

def get_client_ip(
    request: HttpRequest,
    proxy_order: Literal["left-most", "right-most"] = "left-most",
    proxy_count: int | None = None,
    proxy_trusted_ips: Iterable[str] | None = None,
    request_header_order: Iterable[str] | None = None,
) -> tuple[str | None, bool]: ...

__all__ = (
    "AnonThrottle",
    "AuthThrottle",
    "BaseThrottle",
    "SimpleThrottle",
    "throttling",
)

import math
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from http import HTTPStatus
from typing import Any, Literal, cast

from asgiref.sync import async_to_sync, iscoroutinefunction
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext_lazy as _

from app.utils.shorthands import parse_durations


class BaseThrottle(ABC):
    """Base interface for throttling implementations.

    Abstract base class that defines the interface for all throttling mechanisms.
    Implementations must provide the allow_request method to determine whether a request
    should be allowed or throttled.
    """

    @abstractmethod
    async def allow_request(
        self,
        request: HttpRequest,
        now: float,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> tuple[Literal[True], None] | tuple[Literal[False], float | None]:
        """Determine whether a request is allowed or not.

        Args:
            request (HttpRequest): The request to check.
            now (float): The current time.
            args (tuple[Any, ...] | None): The arguments received by the decorated view.
            kwargs (dict[str, Any] | None): The keyword arguments received by the
                decorated view.

        Returns:
            A tuple ``(is_allowed, duration)`` containing:
                - ``is_allowed``: Whether the request is allowed.
                - ``duration``: How long the request will be throttled if ``is_allowed``
                  is ``False``.
        """


@dataclass(slots=True)
class State:
    """State of a single token bucket used in rate limiting.

    Attributes:
        tokens: Current number of tokens available in the bucket.
        last_refill: Timestamp of the last token refill operation.
    """

    tokens: float
    last_refill: float


@dataclass(frozen=True, slots=True)
class StateStore:
    """Token bucket storage with LRU behavior.

    Stores token bucket states with a maximum size limit. When the store is full, the
    least recently used state is evicted to make room for new states. This ensures
    memory usage remains bounded while maintaining efficient access.

    Attributes:
        max_size: Maximum number of states to store.
        states: OrderedDict backing the LRU cache.
    """

    max_size: int
    states: OrderedDict[str, State] = field(default_factory=OrderedDict, init=False)

    def get(self, key: str) -> State | None:
        """Get a state by key.

        Retrieves the state associated with the given key and marks it as recently used
        in the LRU cache.

        Args:
            key: The cache key to retrieve.

        Returns:
            The State object if found, None otherwise.
        """
        states = self.states
        if key in states:
            states.move_to_end(key)
            return states[key]
        return None

    def set(self, key: str, state: State) -> None:
        """Set a state by key.

        Stores the state with the given key and marks it as recently used. If the store
        is at maximum capacity, the least recently used state is evicted.

        Args:
            key: The cache key to store under.
            state: The State object to store.
        """
        states = self.states
        states[key] = state
        states.move_to_end(key)
        if len(states) > self.max_size:
            states.popitem(last=False)


class SimpleThrottle(BaseThrottle, ABC):
    """Throttling with in-memory storage and token bucket strategy.

    Implements rate limiting using the token bucket algorithm with sharded in-memory
    storage for thread safety and performance. The storage uses an LRU eviction policy
    to bound memory usage.

    Note:
        The throttling state is stored in-memory and will not be shared across multiple
        processes. If the same throttle instance is used to throttle different
        endpoints, they will share the same rate limit.

    Args:
        rate: The rate at which the throttle is applied. E.g.: ``10/s``, ``200/5min``.
        max_size: The maximum number of records to hold in memory.
        shards: The number of shards to use for records storage.
    """

    def __init__(
        self,
        rate: str,
        /,
        *,
        max_size: int = 100_000,
        shards: int = 64,
    ) -> None:
        # Normalize shard count to power-of-2 for efficient bit masking.
        shards = 1 << (max(shards, 1) - 1).bit_length()

        self._limit, self._window = self.parse_rate(rate)
        self._mask = shards - 1  # Bitmask for shard selection: e.g., 63 for 64 shards.

        # Distribute max_size across shards, with some shards getting extra capacity.
        base = max(1, max_size // shards)
        extra = max(0, max_size - base * shards)
        self._shards: list[tuple[threading.Lock, StateStore]] = [
            (threading.Lock(), StateStore(max_size=base + (i < extra)))
            for i in range(shards)
        ]

    @abstractmethod
    async def get_cache_key(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> str | None:
        """Get the cache key for this request.

        Determines the unique identifier for rate limiting this request. Returns
        ``None`` to skip throttling for this request.

        Args:
            request: The HTTP request to generate a key for.
            args: The arguments received by the decorated view.
            kwargs: The keyword arguments received by the decorated view.

        Returns:
            A string cache key or ``None`` to skip throttling.
        """

    async def allow_request(
        self,
        request: HttpRequest,
        now: float,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> tuple[Literal[True], None] | tuple[Literal[False], float | None]:
        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}

        key = await self.get_cache_key(request, *args, **kwargs)
        if key is None:
            return True, None

        rate = self._limit / self._window

        # Select shard using hash & bitmask for even distribution.
        lock, shard = self._shards[hash(key) & self._mask]
        with lock:
            state = shard.get(key)
            if state is None:
                # New bucket: start with full tokens.
                state = State(tokens=self._limit, last_refill=now)
            else:
                # Refill tokens based on elapsed time.
                delta = now - state.last_refill
                state.tokens = min(state.tokens + delta * rate, self._limit)
                state.last_refill = now

            if state.tokens >= 1.0:
                # Request allowed: consume one token.
                state.tokens -= 1.0
                shard.set(key, state)
                return True, None

            # Request denied: calculate retry delay.
            needed = 1.0 - state.tokens
            retry_after = needed / rate
            return False, retry_after

    @classmethod
    def parse_rate(cls, rate: str) -> tuple[int, float]:
        """Parse a rate string like ``100/s`` into a tuple ``(limit, window)``.

        >>> SimpleThrottle.parse_rate("100/s")
        (100, 1.0)
        >>> SimpleThrottle.parse_rate("20/5min")
        (20, 300.0)
        >>> SimpleThrottle.parse_rate("1 / HR")
        (1, 3600.0)
        >>> SimpleThrottle.parse_rate("10")
        Traceback (most recent call last):
         ...
        ValueError: Invalid rate: 10
        >>> SimpleThrottle.parse_rate("0/s")
        Traceback (most recent call last):
         ...
        ValueError: Invalid rate: 0/s
        >>> SimpleThrottle.parse_rate("10/0s")
        Traceback (most recent call last):
         ...
        ValueError: Invalid rate: 10/0s
        """
        try:
            limit_str, window_str = rate.split("/", maxsplit=1)

            limit = int(limit_str.strip())
            if limit < 1:
                raise ValueError(f"Invalid limit: {limit}, must be >= 1.")

            window = parse_durations(window_str.strip().lower()).total_seconds()
            if window <= 0:
                raise ValueError(f"Invalid window: {window}, must be > 0.")
        except ValueError as exc:
            raise ValueError(f"Invalid rate: {rate}") from exc
        return limit, window


class AuthThrottle(SimpleThrottle):
    """Throttling authenticated requests only. Use user ID as identifier.

    Applies rate limiting only to authenticated requests, using the user's primary key
    as the unique identifier. Unauthenticated requests are not throttled by this
    implementation.
    """

    async def get_cache_key(
        self,
        request: HttpRequest,
        *_: Any,
        **__: Any,
    ) -> str | None:
        user = await request.auser()
        if not user.is_authenticated:
            return None

        return str(user.pk)


class AnonThrottle(SimpleThrottle):
    """Throttling unauthenticated requests only. Use client IP as identifier.

    Applies rate limiting only to unauthenticated requests, using the client's IP
    address as the unique identifier. Authenticated requests are not throttled by this
    implementation.
    """

    async def get_cache_key(
        self,
        request: HttpRequest,
        *_: Any,
        **__: Any,
    ) -> str | None:
        user = await request.auser()
        if user.is_authenticated:
            return None

        client_ip: str | None = getattr(request, "client_ip", None)
        return client_ip


def throttling[F: Callable[..., Any]](*throttles: BaseThrottle) -> Callable[[F], F]:
    """Decorator to apply throttling for Django views.

    This decorator applies multiple throttles to a view function. If any throttle
    denies the request, a 429 Too Many Requests response is returned immediately.

    Note:
        - If ``DEBUG=True``, throttling will not be enforced.
        - Superuser will not be throttled.

    Args:
        throttles: List of throttles to apply.

    Returns:
        The decorated view function.

    Example::

        @throttling(AnonThrottle("100/s"))
        def my_view(request): ...

        @throttling(
            AnonThrottle("100/s"),
            AuthThrottle("1000/s"),
        )
        def my_view(request): ...
    """

    async def check_throttle(
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse | None:
        # Skip throttling in debug mode.
        if settings.DEBUG:
            return None

        # Skip throttling for superusers.
        user = await request.auser()
        if user.is_superuser:
            return None

        now = time.monotonic()
        waits: list[float | None] = []
        for throttle in throttles:
            ok, wait = await throttle.allow_request(request, now, args, kwargs)
            if not ok:
                waits.append(wait)

        # All throttles allowed the request.
        if not waits:
            return None

        # Create 429 response with Retry-After header.
        response = JsonResponse(
            {
                "message": _("Too many requests."),
            },
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
        # Use the longest wait time from all throttles.
        wait = max([wait for wait in waits if wait is not None], default=None)
        if wait is not None:
            response["Retry-After"] = str(max(1, math.ceil(wait)))
        return response

    def decorator(view_func: F) -> F:
        if iscoroutinefunction(view_func):

            @wraps(view_func)
            async def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
                throttle_response = await check_throttle(
                    request,
                    *args,
                    **kwargs,
                )
                if throttle_response is not None:
                    return throttle_response

                return await view_func(request, *args, **kwargs)
        else:

            @wraps(view_func)
            def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
                throttle_response = async_to_sync(check_throttle)(
                    request,
                    *args,
                    **kwargs,
                )
                if throttle_response is not None:
                    return throttle_response

                return view_func(request, *args, **kwargs)

        return cast(F, wrapped)

    return decorator

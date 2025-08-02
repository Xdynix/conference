"""Authorization decorators."""

__all__ = (
    "Authorization",
    "RequestTest",
    "authorization",
    "has_permissions",
    "is_authenticated",
    "is_superuser",
)

from collections.abc import Awaitable, Callable
from functools import wraps
from http import HTTPStatus
from typing import Concatenate, ParamSpec, Self, TypeVar, cast, overload

from asgiref.sync import async_to_sync, iscoroutinefunction, sync_to_async
from django.utils.translation import gettext as _
from ninja.errors import HttpError

from app.core.services import PermissionService
from app.core.types import HttpRequest

RequestTest = Callable[[HttpRequest], bool]

P = ParamSpec("P")
R = TypeVar("R")
View = Callable[Concatenate[HttpRequest, P], R]


class Authorization:
    """Decorator for adding authorization checks to Django views.

    This decorator wraps a Django view and applies a custom authorization check defined
    by a callable. The callable is expected to take an ``HttpRequest`` and return a
    boolean indicating whether the request is authorized. If the check fails, an
    ``HttpError`` with a status code of 403 is raised.

    If the callable is synchronous-only (e.g., it involves Django ORM queries),
    ``async_unsafe`` must be set to ``True``.

    In addition to being used directly as a decorator, instances of this class can be
    combined with logical operators (``~``, ``&``, ``|``) to build more complex
    authorization conditions.

    Examples:
        >>> is_read = Authorization(lambda r: r.method == "GET", async_unsafe=False)
        >>> @is_read
        ... def readonly_view(request):
        ...     ... # Actual view logic

        >>> is_staff = Authorization(lambda r: r.user.is_staff, async_unsafe=True)
        >>> @(is_read | is_staff)
        ... def staff_writable_view(request):
        ...     ... # Actual view logic
    """

    def __init__(self, request_test: RequestTest, /, *, async_unsafe: bool) -> None:
        self.request_test = request_test
        self.async_unsafe = async_unsafe

    @overload
    def __call__(self, view: View[P, Awaitable[R]]) -> View[P, Awaitable[R]]: ...

    @overload
    def __call__(self, view: View[P, R]) -> View[P, R]: ...

    def __call__(self, view: View[P, R]) -> View[P, R] | View[P, Awaitable[R]]:
        if iscoroutinefunction(view):

            @wraps(view)
            async def async_wrapper(
                request: HttpRequest,
                /,
                *args: P.args,
                **kwargs: P.kwargs,
            ) -> R:
                if self.async_unsafe:
                    pass_test = await sync_to_async(self.request_test)(request)
                else:
                    pass_test = self.request_test(request)
                if not pass_test:
                    raise self.get_error()
                return cast(R, await view(request, *args, **kwargs))

            return async_wrapper

        @wraps(view)
        def wrapper(request: HttpRequest, /, *args: P.args, **kwargs: P.kwargs) -> R:
            if not self.request_test(request):
                raise self.get_error()
            return view(request, *args, **kwargs)

        return wrapper

    def __invert__(self) -> Self:
        def request_test(request: HttpRequest) -> bool:
            return not self.request_test(request)

        return type(self)(request_test, async_unsafe=self.async_unsafe)

    def __and__(self, other: Self) -> Self:
        def request_test(request: HttpRequest) -> bool:
            return self.request_test(request) and other.request_test(request)

        return type(self)(
            request_test,
            async_unsafe=self.async_unsafe or other.async_unsafe,
        )

    def __or__(self, other: Self) -> Self:
        def request_test(request: HttpRequest) -> bool:
            return self.request_test(request) or other.request_test(request)

        return type(self)(
            request_test,
            async_unsafe=self.async_unsafe or other.async_unsafe,
        )

    @classmethod
    def get_error(cls) -> HttpError:
        return HttpError(
            message=_("You are not allowed to perform this action."),
            status_code=HTTPStatus.FORBIDDEN,
        )


@overload
def authorization(
    request_test: RequestTest,
    /,
    *,
    async_unsafe: bool = False,
) -> Authorization: ...


@overload
def authorization(
    *,
    async_unsafe: bool = False,
) -> Callable[[RequestTest], Authorization]: ...


def authorization(
    request_test: RequestTest | None = None,
    /,
    *,
    async_unsafe: bool = False,
) -> Authorization | Callable[[RequestTest], Authorization]:
    """Shortcut for creating an ``Authorization`` from a test function.

    It can be used directly as a decorator on the test function or called with keyword
    arguments to return a decorator.

    Examples:
        >>> @authorization
        ... def is_safe_method(request: HttpRequest) -> bool:
        ...     return request.method in ("GET", "HEAD")

        >>> @authorization(async_unsafe=True)
        ... def is_staff(request: HttpRequest) -> bool:
        ...     return request.user.is_staff
    """
    if request_test is not None:
        return Authorization(request_test, async_unsafe=async_unsafe)

    def decorator(func: RequestTest) -> Authorization:
        return Authorization(func, async_unsafe=async_unsafe)

    return decorator


@authorization(async_unsafe=True)
def is_authenticated(request: HttpRequest) -> bool:
    return request.user.is_authenticated


@authorization(async_unsafe=True)
def is_superuser(request: HttpRequest) -> bool:
    user = request.user
    return user.is_authenticated and user.is_superuser


def has_permissions(*permissions: str) -> Authorization:
    @authorization(async_unsafe=True)
    @async_to_sync
    async def check_permissions(request: HttpRequest) -> bool:
        user = await request.auser()
        user_permissions = await PermissionService.get_permissions(user)
        return all(permission in user_permissions for permission in permissions)

    return check_permissions

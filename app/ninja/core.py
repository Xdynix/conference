from collections.abc import Callable
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, ParamSpec, Self, TypeVar, cast

from django.conf import settings
from django.core.exceptions import PermissionDenied
from ninja import NinjaAPI, Router
from ninja.operation import Operation

from app.ninja.errors import set_exception_handlers
from app.ninja.json import ORJSONParser, ORJSONRenderer

P = ParamSpec("P")
R = TypeVar("R")


def superuser_required[F: Callable[..., Any]](view_func: F) -> F:  # pragma: no cover
    if iscoroutinefunction(view_func):

        @wraps(view_func)
        async def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            user = await request.auser()
            if not (user.is_active and user.is_superuser):
                raise PermissionDenied

            return await view_func(request, *args, **kwargs)
    else:

        @wraps(view_func)
        def wrapped(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            user = request.user
            if not (user.is_active and user.is_superuser):
                raise PermissionDenied

            return view_func(request, *args, **kwargs)

    return cast(F, wrapped)


class AppNinjaAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation: Operation) -> str:
        """Use kebab-case function name as operation ID."""
        return operation.view_func.__name__.replace("_", "-")

    def get_operation_url_name(self, operation: Operation, router: Router) -> str:
        """Generate kebab-case URL name."""
        return super().get_operation_url_name(operation, router).replace("_", "-")

    @classmethod
    def build(cls, urls_namespace: str | None = None) -> Self:
        """Create a configured ``AppNinjaAPI`` instance.

        Args:
            urls_namespace: Optional URL namespace. Used in testing to create isolated
                API instances with unique namespaces to avoid URL conflicts when
                registering test routes.
        """
        api = cls(
            title=settings.SITE_NAME,
            urls_namespace=urls_namespace,
            renderer=ORJSONRenderer(),
            parser=ORJSONParser(),
            docs_decorator=None if settings.DEBUG else superuser_required,
        )
        set_exception_handlers(api)
        return api

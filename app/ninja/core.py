from typing import Self

from django.conf import settings
from ninja import NinjaAPI, Router
from ninja.operation import Operation

from app.ninja.errors import set_exception_handlers
from app.ninja.json import ORJSONParser, ORJSONRenderer


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
            # TODO: Consider protect API doc page if `DEBUG=False`.
        )
        set_exception_handlers(api)
        return api

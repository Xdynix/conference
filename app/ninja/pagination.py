"""Cursor-based pagination for Django Ninja APIs."""

import warnings
from abc import ABC, abstractmethod
from typing import Any, Literal, assert_never

from django.db.models import Model, QuerySet
from django.http import HttpRequest
from ninja import Field, Schema
from ninja.pagination import AsyncPaginationBase


class CursorPaginationBase(AsyncPaginationBase, ABC):
    class Input(Schema):
        page_token: Any | None = None
        page_size: int = 100
        order: Literal["desc", "asc"] = "desc"

    class Output(Schema):
        items: list[Any]
        next_page_token: Any | None = None

    @abstractmethod
    async def make_page(
        self,
        items: list[Any],
        pagination: Schema,
        request: HttpRequest,
    ) -> dict[str, Any]: ...


def cursor_pagination(
    *,
    cursor_field: str = "pk",
    cursor_type: type = str,
) -> type[CursorPaginationBase]:
    class CursorPagination[ModelT: Model](CursorPaginationBase):
        """Cursor-based pagination using model field values as page tokens.

        Implements stable pagination by using a unique field value (cursor) to mark the
        position in the result set. The next page starts from the last item's cursor
        value, making pagination resilient to insertions and deletions.

        The ``cursor_field`` must be unique and sortable. Non-unique fields will cause
        undefined behavior, potentially skipping or duplicating items.

        For predictable behavior when items are added during pagination, the cursor
        field should be monotonic (strictly increasing, e.g., auto-incrementing primary
        key or ULID). With monotonic fields and descending order, newly created items
        consistently do not appear in subsequent pages. Clients should refresh from the
        first page to see newly inserted records. With non-monotonic fields (e.g.,
        username, email), newly created items may appear inconsistently depending on
        their sort position.

        Note: Plain timestamp fields (``auto_now_add``) are generally not unique since
        multiple records can share the same timestamp. Use a uniqueness-guaranteed
        field.

        This paginator always orders by ``cursor_field`` according to the requested
        direction, replacing any prior queryset ordering.
        """

        class Input(Schema):
            """Pagination input parameters."""

            page_token: cursor_type | None = None  # type: ignore[valid-type]
            page_size: int = Field(100, ge=1, le=1000)
            order: Literal["desc", "asc"] = "desc"

        class Output(Schema):
            """Pagination output with items and next page token."""

            items: list[Any]
            next_page_token: cursor_type | None  # type: ignore[valid-type]

        def prepare_queryset(
            self,
            queryset: QuerySet[ModelT],
            pagination: Input,
            request: HttpRequest,  # noqa: ARG002
        ) -> QuerySet[ModelT]:
            """Apply cursor-based ordering and filtering to the queryset."""
            if queryset.ordered:
                warnings.warn(
                    (
                        f"{type(self).__name__} ignores existing queryset ordering "
                        "and always orders by the configured cursor field."
                    ),
                    UserWarning,
                    stacklevel=2,
                )

            page_token = pagination.page_token

            # Apply ordering and cursor filtering.
            match pagination.order:
                case "asc":
                    queryset = queryset.order_by(cursor_field)
                    if page_token is not None:
                        queryset = queryset.filter(
                            **{
                                f"{cursor_field}__gt": page_token,
                            }
                        )
                case "desc":
                    queryset = queryset.order_by(f"-{cursor_field}")
                    if page_token is not None:
                        queryset = queryset.filter(
                            **{
                                f"{cursor_field}__lt": page_token,
                            }
                        )
                case _ as unreachable:
                    assert_never(unreachable)

            return queryset

        async def make_page(
            self,
            items: list[Any],
            pagination: Input,  # type: ignore[override]
            request: HttpRequest,  # noqa: ARG002
        ) -> dict[str, Any]:
            """Build pagination output."""
            if len(items) > pagination.page_size:
                del items[pagination.page_size :]
                next_page_token = getattr(items[-1], cursor_field)
            else:
                next_page_token = None

            return {
                self.items_attribute: items,
                "next_page_token": next_page_token,
            }

        def paginate_queryset(
            self,
            queryset: QuerySet[ModelT],
            pagination: Input,
            request: HttpRequest,
            **__: Any,  # View arguments.
        ) -> dict[str, Any]:  # pragma: no cover
            # Required by base class but not applicable for async-only pagination.
            raise NotImplementedError(
                f"{type(self).__name__} only supports async views. "
                "Use `@paginate` with `async def`."
            )

        async def apaginate_queryset(
            self,
            queryset: QuerySet[ModelT],
            pagination: Input,
            request: HttpRequest,
            **__: Any,  # View arguments.
        ) -> dict[str, Any]:
            queryset = self.prepare_queryset(queryset, pagination, request)

            # Fetch one additional item to determine if there are more.
            items = [item async for item in queryset[: pagination.page_size + 1]]

            return await self.make_page(items, pagination, request)

    return CursorPagination

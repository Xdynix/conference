from typing import Annotated, Any

from django.db.models import QuerySet
from ninja import FilterLookup, FilterSchema, Query
from ninja.pagination import paginate
from ulid import ULID

from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest, EmailStr, Username
from app.ninja.pagination import CursorPagination

from .core import UserResponse, router


class UserPaginator(CursorPagination[User, ULID]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(cursor_field="uid", **kwargs)

    async def make_page(
        self,
        items: list[Any],
        pagination: CursorPagination.Input[ULID],
    ) -> dict[str, Any]:
        page = await super().make_page(items, pagination)
        page[self.items_attribute] = await user_response_registry.dump_many(
            page[self.items_attribute]
        )
        return page


class ListUsersFilters(FilterSchema):
    username: Username | None = None
    email: Annotated[EmailStr | None, FilterLookup(q="email__iexact")] = None
    managed: bool | None = None
    # TODO: Add full-text search across multiple fields (username, email, name).


@router.get(
    "/users",
    response=list[UserResponse],  # type: ignore[valid-type]
    summary="List Users",
    auth=has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL),
)
@paginate(UserPaginator)
async def list_users(
    request: AuthedHttpRequest,  # noqa: ARG001
    filters: Query[ListUsersFilters],
) -> QuerySet[User]:
    """Retrieve a list of users."""
    users = User.objects.filter(is_active=True).all()
    users = filters.filter(users)
    return users

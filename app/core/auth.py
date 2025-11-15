__all__ = (
    "SessionAuth",
    "has_any_roles",
    "is_authenticated",
    "is_superuser",
)


from collections.abc import Awaitable, Callable
from typing import Any

from ninja.errors import AuthorizationError
from ninja.security import SessionAuth as SyncSessionAuth

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.types import HttpRequest


class SessionAuth(SyncSessionAuth):
    """Async authN and authZ using Django session."""

    def __init__(
        self,
        authorize: Callable[[HttpRequest, User], Awaitable[bool]],
    ) -> None:
        super().__init__()
        self.authorize = authorize

    async def __call__(self, request: HttpRequest) -> Any:  # type: ignore[override]
        key = self._get_key(request)
        auth = await self.authenticate(request, key)
        if auth is None:
            return None
        if not await self.authorize(request, auth):
            raise AuthorizationError
        return auth

    async def authenticate(
        self,
        request: HttpRequest,  # type: ignore[override]
        key: str | None,  # noqa: ARG002
    ) -> User | None:
        user = await request.auser()
        if user.is_authenticated and user.is_active:
            return user
        return None


def authorization(func: Callable[[HttpRequest, User], Awaitable[bool]]) -> SessionAuth:
    """Helper decorator to turn authorize function into a session auth instance."""
    return SessionAuth(func)


@authorization
async def is_authenticated(*_: Any) -> bool:
    return True


@authorization
async def is_superuser(_: Any, user: User) -> bool:
    return user.is_superuser


def has_any_roles(*roles: GlobalRole) -> SessionAuth:
    @authorization
    async def _has_any_roles(_: Any, user: User) -> bool:
        if user.is_superuser:
            return True
        return await GlobalRoleAssignment.objects.filter(
            user=user,
            role__in=roles,
        ).aexists()

    return _has_any_roles

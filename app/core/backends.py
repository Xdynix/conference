from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from app.core.models import User


class EmailOrUsernameBackend(ModelBackend):
    """Authenticates using either username or email address.

    If the credential contains '@', it is treated as an email and looked up
    case-insensitively. Otherwise, it is treated as a username.
    """

    @classmethod
    def _get_user(cls, username: str) -> User:
        if "@" in username:
            return User.objects.get(email__iexact=username)
        return User.objects.get(username=username)

    @classmethod
    async def _aget_user(cls, username: str) -> User:
        if "@" in username:
            return await User.objects.aget(email__iexact=username)
        return await User.objects.aget(username=username)

    def authenticate(
        self,
        request: HttpRequest | None,  # noqa: ARG002
        username: str | None = None,
        password: str | None = None,
        **__: Any,
    ) -> User | None:
        if username is None or password is None:
            return None

        try:
            user = self._get_user(username)
        except User.DoesNotExist, User.MultipleObjectsReturned:
            # Run the default password hasher to mitigate timing attacks.
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    async def aauthenticate(
        self,
        request: HttpRequest | None,  # noqa: ARG002
        username: str | None = None,
        password: str | None = None,
        **__: Any,
    ) -> User | None:
        if username is None or password is None:
            return None

        try:
            user = await self._aget_user(username)
        except User.DoesNotExist, User.MultipleObjectsReturned:
            # Run the default password hasher to mitigate timing attacks.
            User().set_password(password)
            return None

        if await user.acheck_password(password) and self.user_can_authenticate(user):
            return user
        return None

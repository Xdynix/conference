__all__ = (
    "AuthedHttpRequest",
    "EmailStr",
    "HttpRequest",
    "Password",
    "Username",
)

from typing import Annotated

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest as DjangoHttpRequest
from pydantic import AfterValidator, Field, SecretStr
from pydantic import EmailStr as DefaultEmailStr

from app.core.models import User


class HttpRequest(DjangoHttpRequest):
    user: User | AnonymousUser

    async def auser(self) -> User | AnonymousUser: ...  # type: ignore[empty-body]  # pragma: no cover


class AuthedHttpRequest(HttpRequest):
    user: User

    async def auser(self) -> User: ...  # type: ignore[empty-body]  # pragma: no cover


user_model_meta = User._meta
username_field = user_model_meta.get_field("username")
password_field = user_model_meta.get_field("password")

Username = Annotated[
    str,
    AfterValidator(User.normalize_username),
    Field(
        description=username_field.help_text.removeprefix("Required. "),
        examples=["user"],
        pattern=User.username_validator.regex,
        min_length=1,
        max_length=username_field.max_length,
    ),
]
Password = Annotated[
    SecretStr,
    Field(
        min_length=1,
        max_length=password_field.max_length,
    ),
]
EmailStr = Annotated[
    DefaultEmailStr,
    AfterValidator(User.objects.normalize_email),
]

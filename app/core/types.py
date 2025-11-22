__all__ = (
    "AuthedHttpRequest",
    "EmailStr",
    "HttpRequest",
    "Password",
    "User",
    "Username",
)

from typing import Annotated, Literal

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest as DjangoHttpRequest
from django.utils.translation import gettext as _
from ninja import Schema
from pydantic import AfterValidator, Field, SecretStr, StringConstraints
from pydantic import EmailStr as DefaultEmailStr
from ulid import ULID

from app.core.models import User as UserModel


class HttpRequest(DjangoHttpRequest):
    user: UserModel | AnonymousUser

    async def auser(self) -> UserModel | AnonymousUser: ...  # type: ignore[empty-body]


class AuthedHttpRequest(HttpRequest):
    user: UserModel

    async def auser(self) -> UserModel: ...  # type: ignore[empty-body]


user_meta = UserModel._meta
username_field = user_meta.get_field("username")
password_field = user_meta.get_field("password")

Username = Annotated[
    str,
    StringConstraints(
        pattern=UserModel.username_validator.regex,
        min_length=1,
        max_length=username_field.max_length,
        strip_whitespace=True,
    ),
    Field(
        description=username_field.help_text.removeprefix("Required. "),
        examples=["user"],
    ),
    AfterValidator(UserModel.normalize_username),
]
Password = Annotated[
    SecretStr,
    StringConstraints(
        min_length=1,
        max_length=password_field.max_length,
    ),
]
EmailStr = Annotated[
    DefaultEmailStr,
    AfterValidator(UserModel.objects.normalize_email),
]


class User(Schema):
    uid: ULID
    username: str = Field(examples=["user"])
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    managed: bool = Field(
        description=_(
            "Whether this user is controlled by the system. "
            "Managed users cannot modify their username and email."
        )
    )

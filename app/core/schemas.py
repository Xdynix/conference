from typing import Literal, Self

from ninja import Field, Schema
from ulid import ULID

from app.core.types import EmailStr, HttpRequest


class User(Schema):
    uid: ULID
    username: str = Field(examples=["user"])
    email: EmailStr | Literal[""] = Field(title="Email Address")
    given_name: str = Field(examples=["John"])
    family_name: str = Field(examples=["Doe"])


class Session(Schema):
    user: User | None

    @classmethod
    async def from_request(cls, request: HttpRequest) -> Self:
        user = await request.auser()
        return cls.model_validate(
            {
                "user": user if user.is_authenticated else None,
            }
        )

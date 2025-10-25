from typing import Literal

from ninja import Field, Schema
from ulid import ULID

from app.core.types import EmailStr


class User(Schema):
    uid: ULID
    username: str = Field(examples=["user"])
    email: EmailStr | Literal[""] = Field(title="Email Address")

__all__ = (
    "UserResponseRegistry",
    "user_response_registry",
)

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from ninja import Field, Schema
from pydantic import create_model
from ulid import ULID

from app.core.models import User
from app.core.types import EmailStr

UserFieldResolver = Callable[[User], Awaitable[Any]]


class BaseUserSchema(Schema):
    uid: ULID
    username: str = Field(examples=["user"])
    email: EmailStr | Literal[""] = Field(title="Email Address")


class UserResponseRegistry:
    """Registry for dynamically extending User API response schemas.

    Allows different apps to register additional fields that should be included in
    ``User`` responses, with custom async resolvers for each field.
    """

    base_schema: type[Schema] = BaseUserSchema
    schema_name: str = "User"

    def __init__(self) -> None:
        self._registry: dict[
            str,
            tuple[Any, UserFieldResolver],
        ] = {}
        self._schema: type[Schema] | None = None

    def register(
        self,
        key: str,
        schema: Any,
        *,
        resolver: UserFieldResolver | None = None,
    ) -> None:
        """Register a new field to include in ``User`` responses.

        Args:
            key: Field name (must be a valid Python identifier).
            schema: Pydantic field schema/type annotation.
            resolver: Optional async function to resolve the field value. Defaults to
                ``getattr(user, key)``.

        Raises:
            RuntimeError: If schema has already been finalized.
            ValueError: If key is invalid, duplicate, or conflicts with base schema.
        """
        if self._schema is not None:
            raise RuntimeError(
                "Cannot register new sub-schemas after "
                "the composed schema has been finalized."
            )

        registry = self._registry

        if not key.isidentifier():
            raise ValueError(f"Invalid key: {key!r} is not a valid identifier.")
        if key in self.base_schema.model_fields:
            raise ValueError(f"Key {key!r} already exists in base schema.")
        if key in registry:
            raise ValueError(f"Key {key!r} already registered.")

        if resolver is None:

            async def resolve(user: User) -> Any:
                return getattr(user, key)

            resolver = resolve

        registry[key] = schema, resolver

    def get_schema(self) -> type[Schema]:
        """Get or create the composed schema with all registered fields.

        Returns:
            Pydantic schema combining base schema with all registered fields.
        """
        if self._schema is not None:
            return self._schema
        additional_fields = {key: schema for key, (schema, _) in self._registry.items()}
        self._schema = create_model(
            self.schema_name,
            __base__=self.base_schema,
            **additional_fields,
        )
        return self._schema

    async def dump(self, user: User) -> dict[str, Any]:
        """Serialize user with all registered fields.

        Args:
            user: User instance to serialize.

        Returns:
            Dictionary with base schema fields and all registered fields.

        Raises:
            Exception: If any resolver fails during field resolution.
        """
        data = self.base_schema.model_validate(user).model_dump()

        resolvers = [(key, resolve) for key, (_, resolve) in self._registry.items()]
        values = await asyncio.gather(*(resolve(user) for _, resolve in resolvers))

        for (key, _), value in zip(resolvers, values, strict=True):
            data[key] = value

        return data


user_response_registry = UserResponseRegistry()

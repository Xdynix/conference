__all__ = (
    "UserResponseRegistry",
    "user_response_registry",
)

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from django.utils.translation import gettext as _
from ninja import Field, Schema
from pydantic import create_model
from ulid import ULID

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.types import EmailStr

UserFieldResolver = Callable[[User], Awaitable[Any]]
UserFieldBatchResolver = Callable[[Sequence[User]], Awaitable[Sequence[Any]]]


class BaseUserSchema(Schema):
    uid: ULID
    username: str = Field(examples=["user"])
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    managed: bool = Field(
        description=_(
            "Whether this user is controlled by the system. "
            "Managed users cannot modify their username and email."
        )
    )


class UserResponseRegistry:
    """Registry for dynamically extending User API response schemas.

    Allows different apps to register additional fields that should be included in
    ``User`` responses, with custom async resolvers for each field. Supports both
    single-user resolvers and batch resolvers for efficient bulk operations.
    """

    base_schema: type[Schema] = BaseUserSchema
    schema_name: str = "User"

    def __init__(self) -> None:
        self._registry: dict[
            str,
            tuple[Any, UserFieldResolver, UserFieldBatchResolver],
        ] = {}
        self._schema: type[Schema] | None = None

    def register(
        self,
        key: str,
        schema: Any,
        *,
        resolver: UserFieldResolver | None = None,
        batch_resolver: UserFieldBatchResolver | None = None,
    ) -> None:
        """Register a new field to include in ``User`` responses.

        Args:
            key: Field name (must be a valid Python identifier).
            schema: Pydantic field schema/type annotation.
            resolver: Optional async function to resolve the field value for a single
                user. Defaults to ``getattr(user, key)``.
            batch_resolver: Optional async function to resolve the field value for
                multiple users in batch. If not provided, falls back to calling the
                resolver for each user individually.

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

        if batch_resolver is None:

            async def batch_resolve(users: Sequence[User]) -> Sequence[Any]:
                return [await resolver(user) for user in users]

            batch_resolver = batch_resolve

        registry[key] = schema, resolver, batch_resolver

    def get_schema(self) -> type[Schema]:
        """Get or create the composed schema with all registered fields.

        Returns:
            Pydantic schema combining base schema with all registered fields.
        """
        if self._schema is not None:
            return self._schema
        additional_fields = {
            key: schema for key, (schema, _, _) in self._registry.items()
        }
        self._schema = create_model(
            self.schema_name,
            __base__=self.base_schema,
            **additional_fields,
        )
        return self._schema

    async def dump(self, user: User) -> dict[str, Any]:
        """Serialize single user with all registered fields.

        Args:
            user: User instance to serialize.

        Returns:
            Dictionary with base schema fields and all registered fields.

        Raises:
            Exception: If any resolver fails during field resolution.
        """
        data = self.base_schema.model_validate(user).model_dump()

        for key, (__, resolve, __) in self._registry.items():
            data[key] = await resolve(user)

        return data

    async def dump_many(self, users: Sequence[User]) -> list[dict[str, Any]]:
        """Serialize multiple users with all registered fields using batch resolvers.

        Args:
            users: Sequence of user instances to serialize.

        Returns:
            List of dictionaries with base schema fields and all registered fields.

        Raises:
            Exception: If any batch resolver fails during field resolution.
            ValueError: If a batch resolver returns a value list whose length does not
                match the number of provided users.
        """
        all_data = [
            self.base_schema.model_validate(user).model_dump() for user in users
        ]

        for key, (__, __, batch_resolve) in self._registry.items():
            values = await batch_resolve(users)
            for data, value in zip(all_data, values, strict=True):
                data[key] = value

        return all_data


user_response_registry = UserResponseRegistry()


async def _get_user_roles(user: User) -> list[str]:
    return [
        role
        async for role in GlobalRoleAssignment.objects.filter(user=user)
        .order_by("role")
        .values_list("role", flat=True)
        .distinct()
    ]


async def _batch_get_user_roles(users: Sequence[User]) -> Sequence[list[str]]:
    user_ids = [user.id for user in users]
    # TODO: Chunk user_ids into batches of ~1000 to avoid SQL parameter limits.
    assignments = GlobalRoleAssignment.objects.filter(user_id__in=user_ids).order_by(
        "role"
    )
    role_map: dict[int, list[str]] = {user.id: [] for user in users}
    async for user_id, role in assignments.values_list("user_id", "role"):
        role_map[user_id].append(role)
    return [role_map[user.id] for user in users]


user_response_registry.register(
    "roles",
    (list[str], Field(examples=[[GlobalRole.ADMIN]])),
    resolver=_get_user_roles,
    batch_resolver=_batch_get_user_roles,
)

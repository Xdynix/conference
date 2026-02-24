__all__ = (
    "CreateUserRegistry",
    "create_user_registry",
)

from collections.abc import Callable
from typing import Any

from ninja import Schema
from pydantic import create_model

from app.core.models import User

type NewUserHandler[T] = Callable[[User, T], Any]


class CreateUserRegistry:
    """Registry for extending user creation with app-specific data and handlers.

    This registry allows Django apps to hook into user creation by registering schemas
    and handlers that create related records (e.g., profiles, preferences) when a new
    user is created. Registered schemas are dynamically merged into request schemas,
    and handlers are dispatched within the user creation transaction.

    Important Considerations:
        1. **Import Order Detection**: Unlike `UserResponseRegistry`, this registry
           extends multiple base schemas (e.g., `BaseCreateRegistrationRequest`,
           `BaseCreateUserRequest`) at import time. This makes it difficult to detect
           missing registrations due to import order issues. Ensure app `ready()`
           methods register handlers before API modules are imported.

        2. **Synchronous Handlers Required**: All handlers run within the database
           transaction that creates the user instance and must be synchronous. If a
           handler needs to make async calls, use `asgiref.sync.async_to_sync` but avoid
           making database queries inside the async context, as this can cause
           transaction and connection issues.
        ```
    """

    def __init__(self) -> None:
        self._registry: dict[
            str,
            tuple[Any, NewUserHandler[Any]],
        ] = {}

    def register[T](
        self,
        key: str,
        schema: type[T] | tuple[type[T], Any] | None = None,
        *,
        handler: NewUserHandler[T],
    ) -> None:
        """Register a schema and handler for user creation extension.

        The registered schema will be added as a field to extended request schemas, and
        the handler will be called during user creation to process the data.

        When ``schema`` is ``None``, no field is added to the request schema and the
        handler receives ``None`` as its payload argument. This is useful for handlers
        that only react to the user's existence (e.g., claiming resources by email)
        without requiring caller-provided data.

        Args:
            key: Unique identifier for this registration. Used as the field name in
                extended request schemas (when a schema is provided) and as the key in
                the dispatch result dict.
            schema: Pydantic field schema/type annotation, or ``None`` to register a
                handler without adding a field to the request schema.
            handler: Synchronous function that receives the created user and payload
                data (or ``None`` when no schema is registered).

        Raises:
            ValueError: If key is not a valid identifier or is already registered.
        """
        registry = self._registry

        if not key.isidentifier():
            raise ValueError(f"Invalid key: {key!r} is not a valid identifier.")
        if key in registry:
            raise ValueError(f"Key {key!r} already registered.")

        registry[key] = schema, handler

    def extend_schema[T: Schema](self, base_schema: type[T], name: str) -> type[T]:
        """Dynamically extend a base schema with all registered fields.

        Creates a new Pydantic model that inherits from the base schema and adds fields
        for each registered key that has a schema. Registrations without a schema are
        skipped (they participate in dispatch only).

        Args:
            base_schema: Base Pydantic schema to extend.
            name: Name for the new schema class.

        Returns:
            New schema class with base fields plus all registered fields.

        Raises:
            ValueError: If any registered key conflicts with a field in the base schema.
        """
        base_fields = base_schema.model_fields
        additional_fields = {}
        for key, (schema, _) in self._registry.items():
            if schema is None:
                continue
            if key in base_fields:
                msg = f"Key {key!r} already exists in base schema."
                raise ValueError(msg)
            additional_fields[key] = schema

        return create_model(
            name,
            __base__=base_schema,
            **additional_fields,
        )

    def dispatch(self, user: User, payload: Any) -> dict[str, Any]:
        """Call all registered handlers with the created user and payload data.

        Iterates through all registered handlers and invokes them with the newly created
        user and their corresponding payload data. Handlers registered without a schema
        receive ``None`` as their payload argument.

        Args:
            user: The newly created user instance.
            payload: Request payload containing data for all registered fields.

        Returns:
            A dict mapping handler keys to their return values. Handlers that return
            ``None`` are omitted.
        """
        detail: dict[str, Any] = {}
        for key, (schema, handle) in self._registry.items():
            data = getattr(payload, key) if schema is not None else None
            result = handle(user, data)
            if result is not None:
                detail[key] = result
        return detail


create_user_registry = CreateUserRegistry()

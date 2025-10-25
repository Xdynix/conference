from typing import Any

import pytest
from faker import Faker
from pydantic import Field
from ulid import ULID

from app.core.models import User
from app.core.registry.user_response import UserResponseRegistry
from tests.helpers import AnyValue


@pytest.mark.django_db(transaction=True)
class TestUserResponseRegistry:
    @pytest.fixture
    def registry(self) -> UserResponseRegistry:
        return UserResponseRegistry()

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    async def test_happy_path(self, registry: UserResponseRegistry, user: User) -> None:
        registry.register("custom_field", str)

        schema = registry.get_schema()
        assert "custom_field" in schema.model_fields

        user.custom_field = "test_value"  # type: ignore[attr-defined]
        data = await registry.dump(user)

        assert data["uid"] == AnyValue(ULID)
        assert data["username"] == user.username
        assert data["email"] == user.email
        assert data["custom_field"] == "test_value"

    async def test_register_with_custom_resolver(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        async def custom_resolver(u: User) -> str:
            return f"custom_{u.username}"

        registry.register("computed_field", str, resolver=custom_resolver)

        data = await registry.dump(user)

        assert data["computed_field"] == f"custom_{user.username}"

    async def test_register_with_optional_field(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        registry.register("optional_field", str | None)

        user.optional_field = None  # type: ignore[attr-defined]
        data = await registry.dump(user)

        assert data["optional_field"] is None

    async def test_register_with_pydantic_field(
        self,
        registry: UserResponseRegistry,
    ) -> None:
        registry.register(
            "described_field",
            (str, Field(description="A custom field")),
        )

        schema = registry.get_schema()

        assert "described_field" in schema.model_fields
        assert schema.model_fields["described_field"].description == "A custom field"

    async def test_empty_registry(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        data = await registry.dump(user)

        assert data["uid"] == AnyValue(ULID)
        assert data["username"] == user.username
        assert data["email"] == user.email

    async def test_schema_finalization_prevents_registration(
        self,
        registry: UserResponseRegistry,
    ) -> None:
        registry.register("field_1", str)
        registry.get_schema()

        with pytest.raises(
            RuntimeError,
            match=(
                "Cannot register new sub-schemas after the "
                "composed schema has been finalized"
            ),
        ):
            registry.register("field_2", str)

    @pytest.mark.parametrize(
        "key",
        [
            "invalid-key",
            "123invalid",
            "invalid key",
        ],
    )
    def test_invalid_key_not_identifier(
        self,
        registry: UserResponseRegistry,
        key: str,
    ) -> None:
        with pytest.raises(ValueError, match="not a valid identifier"):
            registry.register(key, str)

    def test_duplicate_key(self, registry: UserResponseRegistry) -> None:
        registry.register("duplicate", str)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("duplicate", str)

    @pytest.mark.parametrize(
        "key",
        [
            "uid",
            "username",
            "email",
        ],
    )
    def test_key_conflicts_with_base_schema(
        self,
        registry: UserResponseRegistry,
        key: str,
    ) -> None:
        with pytest.raises(ValueError, match="already exists in base schema"):
            registry.register(key, str)

    async def test_resolver_exception_propagates(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        async def failing_resolver(_: User) -> Any:
            raise ValueError("Resolver failed")

        registry.register("failing_field", str, resolver=failing_resolver)

        with pytest.raises(ValueError, match="Resolver failed"):
            await registry.dump(user)

    async def test_default_resolver_missing_attribute(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        registry.register("nonexistent_field", str)

        with pytest.raises(AttributeError):
            await registry.dump(user)

    def test_get_schema_caches_result(self, registry: UserResponseRegistry) -> None:
        registry.register("field_1", str)

        schema_1 = registry.get_schema()
        schema_2 = registry.get_schema()

        assert schema_1 is schema_2

    async def test_complex_type_annotations(
        self,
        registry: UserResponseRegistry,
        user: User,
    ) -> None:
        registry.register("list_field", list[str])
        registry.register("dict_field", dict[str, int])

        user.list_field = ["a", "b", "c"]  # type: ignore[attr-defined]
        user.dict_field = {"key": 123}  # type: ignore[attr-defined]

        data = await registry.dump(user)

        assert data["list_field"] == ["a", "b", "c"]
        assert data["dict_field"] == {"key": 123}

    async def test_resolver_receives_correct_user(
        self,
        registry: UserResponseRegistry,
        faker: Faker,
    ) -> None:
        user_1 = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        user_2 = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        async def resolver(user: User) -> str:
            return user.username

        registry.register("username_copy", str, resolver=resolver)

        data_1 = await registry.dump(user_1)
        data_2 = await registry.dump(user_2)

        assert data_1["username_copy"] == user_1.username
        assert data_2["username_copy"] == user_2.username

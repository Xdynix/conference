from typing import Any
from unittest.mock import MagicMock

import pytest
from faker import Faker
from ninja import Schema

from app.core.models import User
from app.core.registry.create_user import CreateUserRegistry


@pytest.mark.django_db
class TestCreateUserRegistry:
    @pytest.fixture
    def registry(self) -> CreateUserRegistry:
        return CreateUserRegistry()

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(self, registry: CreateUserRegistry, user: User) -> None:
        handler = MagicMock()

        class ProfileSchema(Schema):
            name: str

        registry.register("profile", ProfileSchema, handler=handler)
        schema = registry.extend_schema(Schema, "TestSchema")

        assert "profile" in schema.model_fields

        class MockPayload:
            profile = ProfileSchema(name="Test")

        payload = MockPayload()
        registry.dispatch(user, payload)

        handler.assert_called_once_with(user, payload.profile)

    def test_extend_schema_creates_new_class(
        self,
        registry: CreateUserRegistry,
    ) -> None:
        class BaseSchema(Schema):
            username: str

        class ExtraSchema(Schema):
            bio: str

        registry.register("extra", ExtraSchema, handler=MagicMock())

        extended = registry.extend_schema(BaseSchema, "ExtendedSchema")

        assert extended.__name__ == "ExtendedSchema"
        assert "username" in extended.model_fields
        assert "extra" in extended.model_fields

    def test_extend_schema_with_multiple_fields(
        self,
        registry: CreateUserRegistry,
    ) -> None:
        class Schema1(Schema):
            field1: str

        class Schema2(Schema):
            field2: int

        registry.register("schema1", Schema1, handler=MagicMock())
        registry.register("schema2", Schema2, handler=MagicMock())

        extended = registry.extend_schema(Schema, "MultiFieldSchema")

        assert "schema1" in extended.model_fields
        assert "schema2" in extended.model_fields

    def test_extend_schema_with_empty_registry(
        self,
        registry: CreateUserRegistry,
    ) -> None:
        class BaseSchema(Schema):
            username: str

        extended = registry.extend_schema(BaseSchema, "EmptyExtendedSchema")

        assert extended.__name__ == "EmptyExtendedSchema"
        assert "username" in extended.model_fields
        assert len(extended.model_fields) == 1

    def test_dispatch_calls_all_handlers(
        self,
        registry: CreateUserRegistry,
        user: User,
    ) -> None:
        handler1 = MagicMock()
        handler2 = MagicMock()

        class Schema1(Schema):
            data1: str

        class Schema2(Schema):
            data2: int

        registry.register("field1", Schema1, handler=handler1)
        registry.register("field2", Schema2, handler=handler2)

        class MockPayload:
            field1 = Schema1(data1="test")
            field2 = Schema2(data2=42)

        payload = MockPayload()
        registry.dispatch(user, payload)

        handler1.assert_called_once_with(user, payload.field1)
        handler2.assert_called_once_with(user, payload.field2)

    def test_dispatch_with_empty_registry(
        self,
        registry: CreateUserRegistry,
        user: User,
    ) -> None:
        class MockPayload:
            pass

        payload = MockPayload()
        registry.dispatch(user, payload)

    @pytest.mark.parametrize(
        "key",
        [
            "invalid-key",
            "123invalid",
            "invalid key",
            "invalid.key",
        ],
    )
    def test_invalid_key_not_identifier(
        self,
        registry: CreateUserRegistry,
        key: str,
    ) -> None:
        with pytest.raises(ValueError, match="not a valid identifier"):
            registry.register(key, str, handler=MagicMock())

    def test_duplicate_key(self, registry: CreateUserRegistry) -> None:
        registry.register("duplicate", str, handler=MagicMock())

        with pytest.raises(ValueError, match="already registered"):
            registry.register("duplicate", str, handler=MagicMock())

    @pytest.mark.parametrize(
        "key",
        [
            "username",
            "email",
            "existing_field",
        ],
    )
    def test_key_conflicts_with_base_schema(
        self,
        registry: CreateUserRegistry,
        key: str,
    ) -> None:
        class BaseSchema(Schema):
            username: str
            email: str
            existing_field: int

        registry.register(key, str, handler=MagicMock())

        with pytest.raises(ValueError, match="already exists in base schema"):
            registry.extend_schema(BaseSchema, "ConflictingSchema")

    def test_handler_receives_correct_user(
        self,
        registry: CreateUserRegistry,
        faker: Faker,
    ) -> None:
        user1 = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        user2 = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        handler = MagicMock()

        class DataSchema(Schema):
            value: str

        registry.register("data", DataSchema, handler=handler)

        class MockPayload:
            data = DataSchema(value="test")

        payload1 = MockPayload()
        payload2 = MockPayload()

        registry.dispatch(user1, payload1)
        registry.dispatch(user2, payload2)

        assert handler.call_count == 2
        assert handler.call_args_list[0][0][0] == user1
        assert handler.call_args_list[1][0][0] == user2

    def test_handler_receives_correct_payload(
        self,
        registry: CreateUserRegistry,
        user: User,
    ) -> None:
        handler = MagicMock()

        class DataSchema(Schema):
            name: str
            age: int

        registry.register("data", DataSchema, handler=handler)

        class MockPayload:
            data = DataSchema(name="Alice", age=30)

        payload = MockPayload()
        registry.dispatch(user, payload)

        called_payload = handler.call_args[0][1]
        assert called_payload.name == "Alice"
        assert called_payload.age == 30

    def test_handler_exception_propagates(
        self,
        registry: CreateUserRegistry,
        user: User,
    ) -> None:
        def failing_handler(*_: Any, **__: Any) -> None:
            raise ValueError("Handler failed")

        class DataSchema(Schema):
            value: str

        registry.register("data", DataSchema, handler=failing_handler)

        class MockPayload:
            data = DataSchema(value="test")

        payload = MockPayload()

        with pytest.raises(ValueError, match="Handler failed"):
            registry.dispatch(user, payload)

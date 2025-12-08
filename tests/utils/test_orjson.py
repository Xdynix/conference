from datetime import UTC, datetime

from faker import Faker
from pydantic import HttpUrl
from ulid import ULID

from app.utils.orjson import serializer


def test_datetime(faker: Faker) -> None:
    value = faker.date_time(tzinfo=UTC)
    dumped = serializer.dumps(value)
    loaded = serializer.loads(dumped)
    assert loaded.endswith("Z")
    assert datetime.fromisoformat(loaded) == value


def test_ulid(faker: Faker) -> None:
    value = ULID.from_bytes(faker.binary(length=16))
    dumped = serializer.dumps(value)
    loaded = serializer.loads(dumped)
    assert ULID.from_str(loaded) == value


def test_http_url(faker: Faker) -> None:
    value = HttpUrl(faker.url())
    dumped = serializer.dumps(value)
    loaded = serializer.loads(dumped)
    assert HttpUrl(loaded) == value

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from faker import Faker

from app.core.models import User
from app.core.types import HttpRequest


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


def _make_request(
    rf: RequestFactory,
    user: User | AnonymousUser,
    *,
    include_request_meta: bool = True,
) -> HttpRequest:
    request = rf.get("/")
    request.user = user

    if include_request_meta:
        request.client_ip = "203.0.113.1"  # type: ignore[attr-defined]
        request.request_id = "abc123"  # type: ignore[attr-defined]

    async def auser() -> User | AnonymousUser:
        return user

    request.auser = auser
    return request  # type: ignore[return-value]


@pytest.fixture
def authed_request(rf: RequestFactory, user: User) -> HttpRequest:
    return _make_request(rf, user)


@pytest.fixture
def anon_request(rf: RequestFactory) -> HttpRequest:
    return _make_request(rf, AnonymousUser())


@pytest.fixture
def bare_request(rf: RequestFactory, user: User) -> HttpRequest:
    return _make_request(rf, user, include_request_meta=False)

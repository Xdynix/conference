from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import path
from faker import Faker
from pytest_mock import MockerFixture

from app.utils.throttling import (
    AnonThrottle,
    AuthThrottle,
    BaseThrottle,
    SimpleThrottle,
    throttling,
)
from tests.base import URLConfTestCase, URLPatterns


class MockThrottle(SimpleThrottle):
    async def get_cache_key(self, *_: Any, **__: Any) -> str | None:
        return "test-key"


class TestSimpleThrottleTokenBucket:
    @pytest.fixture
    def throttle(self) -> MockThrottle:
        return MockThrottle("2/s")

    @pytest.fixture
    def mock_request(self, rf: RequestFactory) -> HttpRequest:
        return rf.get("/")

    async def test_allow_request_first_request(
        self,
        throttle: MockThrottle,
        request: HttpRequest,
    ) -> None:
        now = 1000.0

        allowed, wait_time = await throttle.allow_request(request, now)
        assert allowed is True
        assert wait_time is None

    async def test_allow_request_within_limit(
        self,
        throttle: MockThrottle,
        mock_request: HttpRequest,
    ) -> None:
        now = 1000.0

        allowed, _ = await throttle.allow_request(mock_request, now)
        assert allowed is True

        allowed, _ = await throttle.allow_request(mock_request, now)
        assert allowed is True

    async def test_allow_request_exceeds_limit(
        self,
        throttle: MockThrottle,
        mock_request: HttpRequest,
    ) -> None:
        now = 1000.0

        await throttle.allow_request(mock_request, now)
        await throttle.allow_request(mock_request, now)

        allowed, wait_time = await throttle.allow_request(mock_request, now)
        assert allowed is False
        assert wait_time is not None
        assert wait_time > 0

    async def test_allow_request_token_refill(
        self,
        throttle: MockThrottle,
        mock_request: HttpRequest,
    ) -> None:
        now = 1000.0

        await throttle.allow_request(mock_request, now)
        await throttle.allow_request(mock_request, now)

        # Wait for token refill (rate is 2/s, so 0.5s to refill 1 token).
        now += 0.5
        allowed, _ = await throttle.allow_request(mock_request, now)
        assert allowed is True

    async def test_allow_request_skip_throttling(self) -> None:
        class SkipThrottle(SimpleThrottle):
            async def get_cache_key(self, *_: Any, **__: Any) -> str | None:
                return None

        now = 1000.0

        throttle = SkipThrottle("1/s")
        request = MagicMock(spec=HttpRequest)

        allowed, wait_time = await throttle.allow_request(request, now)
        assert allowed is True
        assert wait_time is None
        allowed, wait_time = await throttle.allow_request(request, now)
        assert allowed is True
        assert wait_time is None

    async def test_max_size_eviction(self) -> None:
        allowed_capacity = 10

        class TestThrottle(SimpleThrottle):
            def __init__(self) -> None:
                super().__init__(f"{allowed_capacity}/s", max_size=2, shards=1)

            async def get_cache_key(
                self,
                request: HttpRequest,
                *_: Any,
                **__: Any,
            ) -> str | None:
                return getattr(request, "cache_key", "default-key")

        throttle = TestThrottle()
        now = 1000.0

        request1 = MagicMock(cache_key="key1")
        request2 = MagicMock(cache_key="key2")
        request3 = MagicMock(cache_key="key3")

        # Fill the cache to capacity (max_size=2).
        await throttle.allow_request(request1, now)
        await throttle.allow_request(request2, now)

        # Access key1 again to make it more recently used than key2.
        await throttle.allow_request(request1, now)

        # Add key3, which should evict key2 (least recently used).
        await throttle.allow_request(request3, now)

        # key2 should have been evicted, so it should start with full tokens again.
        # key1 and key3 should still be in cache with reduced tokens.

        # Check that key2 was evicted by seeing it has full tokens again.
        for _ in range(allowed_capacity):
            allowed, _ = await throttle.allow_request(request2, now)
            assert allowed is True

        # Next request should be denied.
        allowed, wait_time = await throttle.allow_request(request2, now)
        assert allowed is False
        assert wait_time is not None


class TestAuthThrottle:
    @pytest.fixture
    def throttle(self) -> AuthThrottle:
        return AuthThrottle("10/s")

    @pytest.mark.django_db(transaction=True)
    async def test_get_cache_key_authenticated_user(
        self,
        mocker: MockerFixture,
        faker: Faker,
        throttle: AuthThrottle,
    ) -> None:
        user = await get_user_model().objects.acreate_user(username=faker.user_name())
        request = mocker.AsyncMock()
        request.auser.return_value = user

        cache_key = await throttle.get_cache_key(request)
        assert cache_key == str(user.pk)

    async def test_get_cache_key_unauthenticated_user(
        self,
        mocker: MockerFixture,
        throttle: AuthThrottle,
    ) -> None:
        request = mocker.AsyncMock()
        request.auser.return_value = AnonymousUser()

        cache_key = await throttle.get_cache_key(request)
        assert cache_key is None


class TestAnonThrottle:
    @pytest.fixture
    def throttle(self) -> AnonThrottle:
        return AnonThrottle("10/s")

    @pytest.fixture
    def mock_get_client_ip(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.utils.throttling.get_client_ip")

    async def test_get_cache_key_unauthenticated_with_routable_ip(
        self,
        mocker: MockerFixture,
        throttle: AnonThrottle,
        mock_get_client_ip: MagicMock,
    ) -> None:
        request = mocker.AsyncMock()
        request.auser.return_value = AnonymousUser()
        mock_get_client_ip.return_value = ("192.168.1.1", True)

        cache_key = await throttle.get_cache_key(request)
        assert cache_key == "192.168.1.1"

    async def test_get_cache_key_unauthenticated_with_non_routable_ip(
        self,
        mocker: MockerFixture,
        throttle: AnonThrottle,
        mock_get_client_ip: MagicMock,
    ) -> None:
        request = mocker.AsyncMock()
        request.auser.return_value = AnonymousUser()
        mock_get_client_ip.return_value = ("127.0.0.1", False)

        cache_key = await throttle.get_cache_key(request)
        assert cache_key is None

    async def test_get_cache_key_unauthenticated_with_no_ip(
        self,
        mocker: MockerFixture,
        throttle: AnonThrottle,
        mock_get_client_ip: MagicMock,
    ) -> None:
        request = mocker.AsyncMock()
        request.auser.return_value = AnonymousUser()
        mock_get_client_ip.return_value = (None, False)

        cache_key = await throttle.get_cache_key(request)
        assert cache_key is None

    @pytest.mark.django_db(transaction=True)
    async def test_get_cache_key_authenticated_user(
        self,
        mocker: MockerFixture,
        faker: Faker,
        throttle: AnonThrottle,
        mock_get_client_ip: MagicMock,
    ) -> None:
        user = await get_user_model().objects.acreate_user(username=faker.user_name())
        request = mocker.AsyncMock()
        request.auser.return_value = user

        cache_key = await throttle.get_cache_key(request)
        assert cache_key is None
        mock_get_client_ip.assert_not_called()


class TestThrottlingDecorator(URLConfTestCase):
    @staticmethod
    def sync_view(_: Any) -> HttpResponse:
        return HttpResponse("OK")

    @staticmethod
    async def async_view(_: Any) -> HttpResponse:
        return HttpResponse("OK")

    @pytest.fixture
    def mock_throttle(self) -> AsyncMock:
        throttle = AsyncMock(spec=BaseThrottle)
        throttle.allow_request.return_value = (True, None)
        return throttle

    @pytest.fixture
    def denying_throttle(self) -> AsyncMock:
        throttle = AsyncMock(spec=BaseThrottle)
        throttle.allow_request.return_value = (False, 5.0)
        return throttle

    @pytest.fixture
    def urlpatterns(
        self,
        mock_throttle: AsyncMock,
        denying_throttle: AsyncMock,
    ) -> URLPatterns:
        return [
            path("sync/", throttling(mock_throttle)(self.sync_view)),
            path("async/", throttling(mock_throttle)(self.async_view)),
            path("sync-denied/", throttling(denying_throttle)(self.sync_view)),
            path("async-denied/", throttling(denying_throttle)(self.async_view)),
        ]

    @pytest.fixture
    def mock_request(self) -> AsyncMock:
        request = AsyncMock()
        request.auser.return_value = AnonymousUser()
        return request

    @pytest.mark.parametrize("url", ["/sync/", "/async/"])
    def test_throttling_decorator_allowed(
        self,
        client: Client,
        mock_throttle: AsyncMock,
        url: str,
    ) -> None:
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"OK"
        mock_throttle.allow_request.assert_called_once()

    @pytest.mark.parametrize("url", ["/sync-denied/", "/async-denied/"])
    def test_throttling_decorator_denied(
        self,
        client: Client,
        settings: LazySettings,
        denying_throttle: AsyncMock,
        url: str,
    ) -> None:
        settings.DEBUG = False

        response = client.get(url)

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert response.json() == {"message": "Too many requests."}
        assert response["Retry-After"] == "5"
        denying_throttle.allow_request.assert_called_once()

    @pytest.mark.parametrize("url", ["/sync-denied/", "/async-denied/"])
    def test_throttling_decorator_debug_mode_bypass(
        self,
        client: Client,
        settings: LazySettings,
        denying_throttle: AsyncMock,
        url: str,
    ) -> None:
        settings.DEBUG = True

        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        denying_throttle.allow_request.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize("url", ["/sync-denied/", "/async-denied/"])
    def test_throttling_decorator_superuser_bypass(
        self,
        faker: Faker,
        client: Client,
        settings: LazySettings,
        denying_throttle: AsyncMock,
        url: str,
    ) -> None:
        settings.DEBUG = False

        user = get_user_model().objects.create_superuser(username=faker.user_name())
        client.force_login(user)

        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        denying_throttle.allow_request.assert_not_called()

    def test_throttling_decorator_multiple_throttles(
        self,
        settings: LazySettings,
        mock_request: AsyncMock,
    ) -> None:
        settings.DEBUG = False

        throttle1 = AsyncMock(spec=BaseThrottle)
        throttle1.allow_request.return_value = (True, None)
        throttle2 = AsyncMock(spec=BaseThrottle)
        throttle2.allow_request.return_value = (False, 3.0)

        @throttling(throttle1, throttle2)
        def view(_: Any) -> HttpResponse:
            return HttpResponse("OK")

        response = view(mock_request)

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert response["Retry-After"] == "3"
        throttle1.allow_request.assert_called_once()
        throttle2.allow_request.assert_called_once()

    def test_throttling_decorator_longest_wait_time(
        self,
        settings: LazySettings,
        mock_request: AsyncMock,
    ) -> None:
        settings.DEBUG = False

        throttle1 = AsyncMock(spec=BaseThrottle)
        throttle1.allow_request.return_value = (False, 2.0)
        throttle2 = AsyncMock(spec=BaseThrottle)
        throttle2.allow_request.return_value = (False, 5.5)

        @throttling(throttle1, throttle2)
        def view(_: Any) -> HttpResponse:
            return HttpResponse("OK")

        response = view(mock_request)

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert response["Retry-After"] == "6"  # Math.ceil(5.5)

    def test_throttling_decorator_none_wait_time(
        self,
        settings: LazySettings,
        mock_request: AsyncMock,
    ) -> None:
        settings.DEBUG = False

        throttle = AsyncMock(spec=BaseThrottle)
        throttle.allow_request.return_value = (False, None)

        @throttling(throttle)
        def view(_: Any) -> HttpResponse:
            return HttpResponse("OK")

        response = view(mock_request)

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert "Retry-After" not in response

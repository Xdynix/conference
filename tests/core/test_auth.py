from asyncio import get_running_loop
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory
from faker import Faker
from ninja import NinjaAPI
from ninja.errors import HttpError
from pytest_mock import MockerFixture

from app.core.auth import (
    Authorization,
    RequestTest,
    authorization,
    has_permissions,
    is_authenticated,
    is_superuser,
)
from app.core.models import Permission, User
from app.core.services import PermissionService
from app.core.types import HttpRequest
from tests.base import URLConfTestCase, URLPatterns
from tests.helpers import any_str, update_object

SyncDummyView = Callable[..., bool]
AsyncDummyView = Callable[..., Awaitable[bool]]


class TestAuthorization:
    @pytest.fixture
    def sync_view(self) -> SyncDummyView:
        def foobar(*_: Any) -> bool:
            return True

        return foobar

    @pytest.fixture
    def async_view(self) -> AsyncDummyView:
        async def foobar(*_: Any) -> bool:
            return True

        return foobar

    @pytest.fixture
    def req(self, rf: RequestFactory) -> HttpRequest:
        request = cast(HttpRequest, rf.get("/"))
        request.user = AnonymousUser()
        return request

    @classmethod
    def get_request_test(
        cls,
        result: bool,
        *,
        async_unsafe: bool = False,
    ) -> RequestTest:
        def request_test(_: Any) -> bool:
            if not async_unsafe:
                return result

            try:
                get_running_loop()
            except RuntimeError:
                return result
            else:
                raise RuntimeError("This function is async unsafe.")

        return request_test

    @pytest.mark.parametrize("authorized", [True, False])
    @pytest.mark.parametrize("async_unsafe", [True, False])
    def test_sync(
        self,
        sync_view: SyncDummyView,
        req: HttpRequest,
        authorized: bool,
        async_unsafe: bool,
    ) -> None:
        request_test = self.get_request_test(authorized, async_unsafe=async_unsafe)
        decorated = authorization(request_test, async_unsafe=async_unsafe)(sync_view)
        if authorized:
            assert decorated(req) is True
        else:
            with pytest.raises(HttpError) as exc_info:
                decorated(req)
                assert exc_info.value.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("authorized", [True, False])
    @pytest.mark.parametrize("async_unsafe", [True, False])
    async def test_async(
        self,
        async_view: AsyncDummyView,
        req: HttpRequest,
        authorized: bool,
        async_unsafe: bool,
    ) -> None:
        request_test = self.get_request_test(authorized, async_unsafe=async_unsafe)
        decorated = authorization(request_test, async_unsafe=async_unsafe)(async_view)
        if authorized:
            assert await decorated(req) is True
        else:
            with pytest.raises(HttpError) as exc_info:
                await decorated(req)
                assert exc_info.value.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("result", [True, False])
    @pytest.mark.parametrize("async_unsafe", [True, False])
    def test_invert(self, req: HttpRequest, result: bool, async_unsafe: bool) -> None:
        auth = authorization(lambda _: result, async_unsafe=async_unsafe)
        inverted = ~auth
        assert inverted.request_test(req) is not result
        assert inverted.async_unsafe is async_unsafe

    @pytest.mark.parametrize("result_1", [True, False])
    @pytest.mark.parametrize("async_unsafe_1", [True, False])
    @pytest.mark.parametrize("result_2", [True, False])
    @pytest.mark.parametrize("async_unsafe_2", [True, False])
    def test_and(
        self,
        req: HttpRequest,
        result_1: bool,
        async_unsafe_1: bool,
        result_2: bool,
        async_unsafe_2: bool,
    ) -> None:
        auth_1 = authorization(lambda _: result_1, async_unsafe=async_unsafe_1)
        auth_2 = authorization(lambda _: result_2, async_unsafe=async_unsafe_2)
        combined = auth_1 & auth_2
        assert combined.request_test(req) is (result_1 and result_2)
        assert combined.async_unsafe is (async_unsafe_1 or async_unsafe_2)

    @pytest.mark.parametrize("result_1", [True, False])
    @pytest.mark.parametrize("async_unsafe_1", [True, False])
    @pytest.mark.parametrize("result_2", [True, False])
    @pytest.mark.parametrize("async_unsafe_2", [True, False])
    def test_or(
        self,
        req: HttpRequest,
        result_1: bool,
        async_unsafe_1: bool,
        result_2: bool,
        async_unsafe_2: bool,
    ) -> None:
        auth_1 = authorization(lambda _: result_1, async_unsafe=async_unsafe_1)
        auth_2 = authorization(lambda _: result_2, async_unsafe=async_unsafe_2)
        combined = auth_1 | auth_2
        assert combined.request_test(req) is (result_1 or result_2)
        assert combined.async_unsafe is (async_unsafe_1 or async_unsafe_2)


@pytest.mark.parametrize("async_unsafe", [True, False])
def test_authorization(async_unsafe: bool) -> None:
    def request_test(_: Any) -> bool:
        return True

    auth_directly = authorization(request_test)
    assert auth_directly.request_test is request_test
    assert auth_directly.async_unsafe is False

    auth_no_argument = authorization()(request_test)
    assert auth_no_argument.request_test is request_test
    assert auth_no_argument.async_unsafe is False

    auth_with_kw_argument = authorization(async_unsafe=async_unsafe)(request_test)
    assert auth_with_kw_argument.request_test is request_test
    assert auth_with_kw_argument.async_unsafe is async_unsafe

    auth_with_all_argument = authorization(request_test, async_unsafe=async_unsafe)
    assert auth_with_all_argument.request_test is request_test
    assert auth_with_all_argument.async_unsafe is async_unsafe


SYNC_PATH = "/sync"
ASYNC_PATH = "/async"
ALL_PATHS = [SYNC_PATH, ASYNC_PATH]


@pytest.mark.django_db(transaction=True)
class PermissionTestCase(URLConfTestCase):
    auth: Authorization

    @classmethod
    def assert_response_is_ok(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.OK
        assert response.json() == "OK"

    @classmethod
    def assert_response_is_forbidden(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": any_str}

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get(SYNC_PATH)
        @self.auth
        def sync_view(*_: Any) -> str:
            return "OK"

        @api.get(ASYNC_PATH)
        @self.auth
        async def async_view(*_: Any) -> str:
            return "OK"

        # Intentionally imported as local to prevent it
        # from occupying the global namespace.
        from django.urls import path

        return [path("", api.urls)]

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())


class TestIsAuthenticated(PermissionTestCase):
    auth = is_authenticated

    @pytest.mark.parametrize("path", ALL_PATHS)
    @pytest.mark.parametrize("authenticated", [True, False])
    def test_smoke(
        self,
        client: Client,
        user: User,
        path: str,
        authenticated: bool,
    ) -> None:
        if authenticated:
            client.force_login(user)
        response = client.get(path)
        if authenticated:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestIsSuperuser(PermissionTestCase):
    auth = is_superuser

    @pytest.mark.parametrize("path", ALL_PATHS)
    @pytest.mark.parametrize("superuser", [True, False])
    def test_smoke(
        self,
        client: Client,
        user: User,
        path: str,
        superuser: bool,
    ) -> None:
        update_object(user, is_superuser=superuser)
        client.force_login(user)
        response = client.get(path)
        if superuser:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestHasPermissionsSingle(PermissionTestCase):
    auth = has_permissions("read")

    @pytest.mark.parametrize("path", ALL_PATHS)
    def test_unauthenticated_denied(self, client: Client, path: str) -> None:
        response = client.get(path)
        self.assert_response_is_forbidden(response)

    @pytest.mark.parametrize("path", ALL_PATHS)
    def test_superuser_allowed(self, client: Client, user: User, path: str) -> None:
        update_object(user, is_superuser=True)
        Permission.objects.create(key="read")
        client.force_login(user)
        response = client.get(path)
        self.assert_response_is_ok(response)

    @pytest.mark.parametrize("path", ALL_PATHS)
    @pytest.mark.parametrize(
        "user_permissions,expected",
        [
            ({"read"}, True),
            ({"read", "write"}, True),
            ({"write"}, False),
            (set(), False),
        ],
    )
    def test_smoke(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        path: str,
        user_permissions: set[str],
        expected: bool,
    ) -> None:
        mocker.patch.object(
            PermissionService,
            "get_permissions",
            return_value=user_permissions,
        )
        client.force_login(user)
        response = client.get(path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestHasPermissionsMulti(PermissionTestCase):
    auth = has_permissions("read", "write")

    @pytest.mark.parametrize("path", ALL_PATHS)
    @pytest.mark.parametrize(
        "user_permissions,expected",
        [
            ({"read"}, False),
            ({"read", "write"}, True),
            ({"write"}, False),
            (set(), False),
        ],
    )
    def test_smoke(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        path: str,
        user_permissions: set[str],
        expected: bool,
    ) -> None:
        mocker.patch.object(
            PermissionService,
            "get_permissions",
            return_value=user_permissions,
        )
        client.force_login(user)
        response = client.get(path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)

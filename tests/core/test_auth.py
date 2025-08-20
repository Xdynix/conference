from http import HTTPStatus
from typing import Any

import pytest
from django.test import Client
from faker import Faker
from ninja import NinjaAPI
from pytest_mock import MockerFixture

from app.core.auth import SessionAuth, has_permissions, is_authenticated, is_superuser
from app.core.models import Permission, User
from app.core.services import PermissionService
from tests.base import URLConfTestCase, URLPatterns
from tests.helpers import any_str, update_object


@pytest.mark.django_db(transaction=True)
class AuthTestCase(URLConfTestCase):
    auth: SessionAuth

    path = "/view"

    @classmethod
    def assert_response_is_ok(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.OK
        assert response.json() == "OK"

    @classmethod
    def assert_response_is_forbidden(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": any_str}

    @classmethod
    def assert_response_is_unauthorized(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": any_str}

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get(self.path, auth=self.auth)
        async def view(*_: Any) -> str:
            return "OK"

        # Intentionally imported as local to prevent it
        # from occupying the global namespace.
        from django.urls import path

        return [path("", api.urls)]

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())


class TestIsAuthenticated(AuthTestCase):
    auth = is_authenticated

    @pytest.mark.parametrize("authenticated", [True, False])
    def test_smoke(
        self,
        client: Client,
        user: User,
        authenticated: bool,
    ) -> None:
        if authenticated:
            client.force_login(user)
        response = client.get(self.path)
        if authenticated:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_unauthorized(response)


class TestIsSuperuser(AuthTestCase):
    auth = is_superuser

    @pytest.mark.parametrize("superuser", [True, False])
    def test_smoke(
        self,
        client: Client,
        user: User,
        superuser: bool,
    ) -> None:
        update_object(user, is_superuser=superuser)
        client.force_login(user)
        response = client.get(self.path)
        if superuser:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestHasPermissionsSingle(AuthTestCase):
    auth = has_permissions("read")

    def test_unauthenticated_denied(self, client: Client) -> None:
        response = client.get(self.path)
        self.assert_response_is_unauthorized(response)

    def test_superuser_allowed(self, client: Client, user: User) -> None:
        update_object(user, is_superuser=True)
        Permission.objects.create(key="read")
        client.force_login(user)
        response = client.get(self.path)
        self.assert_response_is_ok(response)

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
        user_permissions: set[str],
        expected: bool,
    ) -> None:
        mocker.patch.object(
            PermissionService,
            "get_permissions",
            return_value=user_permissions,
        )
        client.force_login(user)
        response = client.get(self.path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestHasPermissionsMulti(AuthTestCase):
    auth = has_permissions("read", "write")

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
        user_permissions: set[str],
        expected: bool,
    ) -> None:
        mocker.patch.object(
            PermissionService,
            "get_permissions",
            return_value=user_permissions,
        )
        client.force_login(user)
        response = client.get(self.path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)

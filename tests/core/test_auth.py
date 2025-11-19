from typing import Any

import pytest
from django.test import Client
from faker import Faker
from ninja import NinjaAPI
from pytest_mock import MockerFixture

from app.core.auth import SessionAuth, has_any_roles, is_authenticated, is_superuser
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.base import ResponseAssertionsMixin, URLConfTestCase, URLPatterns
from tests.helpers import update_object


class TestSessionAuthCompositionAnd:
    async def test_short_circuit_when_left_false(self, mocker: MockerFixture) -> None:
        auth_true = mocker.AsyncMock(return_value=True)
        auth_false = mocker.AsyncMock(return_value=False)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_false) & SessionAuth(auth_true)

        assert await combined.authorize(request, user) is False
        auth_false.assert_called_once()
        auth_true.assert_not_called()

    async def test_requires_both_when_left_true(self, mocker: MockerFixture) -> None:
        auth_left = mocker.AsyncMock(return_value=True)
        auth_right = mocker.AsyncMock(return_value=True)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_left) & SessionAuth(auth_right)

        assert await combined.authorize(request, user) is True
        auth_left.assert_called_once()
        auth_right.assert_called_once()

    async def test_fails_when_right_false(self, mocker: MockerFixture) -> None:
        auth_true = mocker.AsyncMock(return_value=True)
        auth_false = mocker.AsyncMock(return_value=False)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_true) & SessionAuth(auth_false)

        assert await combined.authorize(request, user) is False
        auth_true.assert_called_once()
        auth_false.assert_called_once()


class TestSessionAuthCompositionOr:
    async def test_short_circuit_when_left_true(self, mocker: MockerFixture) -> None:
        auth_true = mocker.AsyncMock(return_value=True)
        auth_false = mocker.AsyncMock(return_value=False)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_true) | SessionAuth(auth_false)

        assert await combined.authorize(request, user) is True
        auth_true.assert_called_once()
        auth_false.assert_not_called()

    async def test_evaluates_right_when_left_false(self, mocker: MockerFixture) -> None:
        auth_true = mocker.AsyncMock(return_value=True)
        auth_false = mocker.AsyncMock(return_value=False)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_false) | SessionAuth(auth_true)

        assert await combined.authorize(request, user) is True
        auth_false.assert_called_once()
        auth_true.assert_called_once()

    async def test_fails_when_both_false(self, mocker: MockerFixture) -> None:
        auth_left = mocker.AsyncMock(return_value=False)
        auth_right = mocker.AsyncMock(return_value=False)
        request = mocker.MagicMock()
        user = mocker.MagicMock()

        combined = SessionAuth(auth_left) | SessionAuth(auth_right)

        assert await combined.authorize(request, user) is False
        auth_left.assert_called_once()
        auth_right.assert_called_once()


@pytest.mark.django_db
class AuthTestCase(ResponseAssertionsMixin, URLConfTestCase):
    auth: SessionAuth

    path = "/view"

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
    @pytest.mark.parametrize("is_active", [True, False])
    def test_smoke(
        self,
        client: Client,
        user: User,
        authenticated: bool,
        is_active: bool,
    ) -> None:
        if authenticated:
            client.force_login(user)
        update_object(user, is_active=is_active)
        response = client.get(self.path)
        if authenticated and is_active:
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


class TestHasAnyRolesSingle(AuthTestCase):
    auth = has_any_roles(GlobalRole.ADMIN)

    def test_unauthenticated_denied(self, client: Client) -> None:
        response = client.get(self.path)
        self.assert_response_is_unauthorized(response)

    def test_superuser_allowed(self, client: Client, user: User) -> None:
        update_object(user, is_superuser=True)
        client.force_login(user)
        response = client.get(self.path)
        self.assert_response_is_ok(response)

    @pytest.mark.parametrize(
        "user_roles,expected",
        [
            ({GlobalRole.ADMIN}, True),
            ({GlobalRole.ADMIN, GlobalRole.READ_ALL}, True),
            ({GlobalRole.READ_ALL}, False),
            (set(), False),
        ],
    )
    def test_smoke(
        self,
        client: Client,
        user: User,
        user_roles: set[GlobalRole],
        expected: bool,
    ) -> None:
        for role in user_roles:
            GlobalRoleAssignment.objects.create(user=user, role=role)
        client.force_login(user)
        response = client.get(self.path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)


class TestHasAnyRolesMulti(AuthTestCase):
    auth = has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)

    def test_unauthenticated_denied(self, client: Client) -> None:
        response = client.get(self.path)
        self.assert_response_is_unauthorized(response)

    def test_superuser_allowed(self, client: Client, user: User) -> None:
        update_object(user, is_superuser=True)
        client.force_login(user)
        response = client.get(self.path)
        self.assert_response_is_ok(response)

    @pytest.mark.parametrize(
        "user_roles,expected",
        [
            ({GlobalRole.ADMIN}, True),
            ({GlobalRole.ADMIN, GlobalRole.READ_ALL}, True),
            ({GlobalRole.READ_ALL}, True),
            (set(), False),
        ],
    )
    def test_smoke(
        self,
        client: Client,
        user: User,
        user_roles: set[GlobalRole],
        expected: bool,
    ) -> None:
        for role in user_roles:
            GlobalRoleAssignment.objects.create(user=user, role=role)
        client.force_login(user)
        response = client.get(self.path)
        if expected:
            self.assert_response_is_ok(response)
        else:
            self.assert_response_is_forbidden(response)

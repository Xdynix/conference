from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.services import UserService
from tests.helpers import any_str, update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


@pytest.fixture
def user_service_set_roles(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(UserService, "set_roles")


@pytest.mark.django_db
class TestUpdateUserRoles:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user-roles", args=[user_id])

    @pytest.fixture
    def admin_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        user_service_set_roles: MagicMock,
        admin_user: User,
    ) -> None:
        roles = [GlobalRole.ADMIN, GlobalRole.READ_ALL]
        api_client.force_login(admin_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": roles},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == any_str
        assert data["username"] == user.username
        assert data["email"] == user.email
        assert data["managed"] is False
        assert data["roles"] == roles

        user_service_set_roles.assert_called_once_with(user=user, roles=roles)

    def test_remove_all_roles(
        self,
        api_client: Client,
        user: User,
        user_service_set_roles: MagicMock,
        admin_user: User,
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": []},
        )
        assert response.status_code == HTTPStatus.OK

        user_service_set_roles.assert_called_once_with(user=user, roles=[])

    def test_update_inactive_user_not_found(
        self,
        api_client: Client,
        user: User,
        user_service_set_roles: MagicMock,
        admin_user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(admin_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_set_roles.assert_not_called()

    def test_nonexistent_user_not_found(
        self,
        api_client: Client,
        user_service_set_roles: MagicMock,
        admin_user: User,
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.put(
            self.path(user_id=ULID()),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_set_roles.assert_not_called()

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_set_roles: MagicMock,
    ) -> None:
        regular_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(regular_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        user_service_set_roles.assert_not_called()

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        user: User,
        user_service_set_roles: MagicMock,
    ) -> None:
        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        user_service_set_roles.assert_not_called()

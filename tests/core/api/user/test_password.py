from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import User
from app.core.services import ApiKeyService, UserService
from app.core.services.user import InvalidPassword
from tests.helpers import update_object


@pytest.fixture
def user_service_update_password(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(UserService, "update_password")


@pytest.fixture
def user_service_change_password(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(UserService, "change_password")


@pytest.fixture
def old_password() -> str:
    return "OldPassword123!"


@pytest.fixture
def user(faker: Faker, old_password: str) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        password=old_password,
    )


@pytest.mark.django_db
class TestSetCurrentUserPassword:
    path = reverse("api-1.0.0:set-current-user-password")

    def test_happy_path(
        self,
        api_client: Client,
        old_password: str,
        user: User,
        user_service_change_password: MagicMock,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={
                "old_password": old_password,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        user_service_change_password.assert_called_once_with(
            user=user,
            old_password=old_password,
            new_password=new_password,
        )
        # Session should remain active after password change.
        assert get_user(api_client) == user

    def test_handle_invalid_old_password(
        self,
        api_client: Client,
        user: User,
        user_service_change_password: MagicMock,
    ) -> None:
        user_service_change_password.side_effect = ValueError("Invalid old password.")
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={
                "old_password": "WrongPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "old_password"]
        assert "Invalid old password" in error["msg"]

        user_service_change_password.assert_called_once()

    def test_handle_invalid_password(
        self,
        api_client: Client,
        old_password: str,
        user: User,
        user_service_change_password: MagicMock,
    ) -> None:
        user_service_change_password.side_effect = InvalidPassword(
            [
                "This password is too short. It must contain at least 8 characters.",
                "This password is too common.",
            ]
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={
                "old_password": old_password,
                "new_password": "weak",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error1, error2] = data["details"]
        assert error1["type"] == "value_error"
        assert error1["loc"] == ["body", "payload", "new_password"]
        assert "too short" in error1["msg"]
        assert error2["type"] == "value_error"
        assert error2["loc"] == ["body", "payload", "new_password"]
        assert "too common" in error2["msg"]

        user_service_change_password.assert_called_once()

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        user_service_change_password: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path,
            data={
                "old_password": "OldPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        user_service_change_password.assert_not_called()

    def test_bearer_auth_rejected(
        self,
        api_client: Client,
        user: User,
        user_service_change_password: MagicMock,
    ) -> None:
        _, plaintext = ApiKeyService.create_key(user)

        response = api_client.post(
            self.path,
            data={"old_password": "x", "new_password": "y"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "API key" in response.json()["message"]

        user_service_change_password.assert_not_called()


@pytest.mark.django_db
class TestSetUserPassword:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:set-user-password", args=[user_id])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        admin_user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path(user_id=user.uid),
            data={"new_password": new_password},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        user_service_update_password.assert_called_once_with(
            user=user,
            new_password=new_password,
        )

    def test_update_inactive_user_not_found(
        self,
        api_client: Client,
        user: User,
        admin_user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update_password.assert_not_called()

    def test_update_superuser_not_found(
        self,
        api_client: Client,
        user: User,
        admin_user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        update_object(user, is_superuser=True)
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update_password.assert_not_called()

    def test_nonexistent_user_not_found(
        self,
        api_client: Client,
        admin_user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path(user_id=ULID()),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update_password.assert_not_called()

    def test_handle_invalid_password(
        self,
        api_client: Client,
        user: User,
        admin_user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        user_service_update_password.side_effect = InvalidPassword(
            [
                "This password is too short. It must contain at least 8 characters.",
                "This password is too common.",
            ]
        )
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path(user_id=user.uid),
            data={"new_password": "weak"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error1, error2] = data["details"]
        assert error1["type"] == "value_error"
        assert error1["loc"] == ["body", "payload", "new_password"]
        assert "too short" in error1["msg"]
        assert error2["type"] == "value_error"
        assert error2["loc"] == ["body", "payload", "new_password"]
        assert "too common" in error2["msg"]

        user_service_update_password.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        user_service_update_password: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        user_service_update_password.assert_not_called()

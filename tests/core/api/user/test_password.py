from http import HTTPStatus

import pytest
from django.contrib.auth import get_user
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import (
    GlobalRole,
    GlobalRoleAssignment,
    User,
)
from tests.helpers import update_object


@pytest.fixture
def old_password() -> str:
    return "OldPassword123!"


@pytest.mark.django_db
class TestUpdateCurrentUserPassword:
    path = reverse("api-1.0.0:update-current-user-password")

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": old_password,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""

        user.refresh_from_db()
        assert user.check_password(new_password)
        assert not user.check_password(old_password)

        assert get_user(api_client) == user

    def test_invalid_old_password(
        self,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": "WrongPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert response_data["details"][0]["type"] == "value_error"
        assert response_data["details"][0]["loc"] == ["body", "payload", "old_password"]
        assert "Invalid old password" in response_data["details"][0]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_weak_new_password(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        mock_validate = mocker.patch(
            "app.core.api.user.password.validate_password",
            side_effect=ValidationError(
                [
                    (
                        "This password is too short. "
                        "It must contain at least 8 characters."
                    ),
                    "This password is too common.",
                ]
            ),
        )
        new_password = "weak"
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": old_password,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert len(response_data["details"]) == 2
        for error in response_data["details"]:
            assert error["type"] == "value_error"
            assert error["loc"] == ["body", "payload", "new_password"]
        assert "too short" in response_data["details"][0]["msg"]
        assert "too common" in response_data["details"][1]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

        mock_validate.assert_called_once_with(new_password, user=user)

    def test_unauthenticated_user_forbidden(self, api_client: Client) -> None:
        response = api_client.put(
            self.path,
            data={
                "old_password": "OldPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUpdateUserPassword:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user-password", args=[user_id])

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    def test_happy_path(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": new_password},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""

        user.refresh_from_db()
        assert user.check_password(new_password)
        assert not user.check_password(old_password)

    def test_change_inactive_user_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_change_superuser_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        update_object(user, is_superuser=True)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_nonexistent_user_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=ULID()),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_weak_new_password(
        self,
        mocker: MockerFixture,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        mock_validate = mocker.patch(
            "app.core.api.user.password.validate_password",
            side_effect=ValidationError(
                [
                    (
                        "This password is too short. "
                        "It must contain at least 8 characters."
                    ),
                    "This password is too common.",
                ]
            ),
        )
        new_password = "weak"
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": new_password},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert len(response_data["details"]) == 2
        for error in response_data["details"]:
            assert error["type"] == "value_error"
            assert error["loc"] == ["body", "payload", "new_password"]
        assert "too short" in response_data["details"][0]["msg"]
        assert "too common" in response_data["details"][1]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

        mock_validate.assert_called_once()

    def test_unauthorized_user_forbidden(self, api_client: Client, user: User) -> None:
        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

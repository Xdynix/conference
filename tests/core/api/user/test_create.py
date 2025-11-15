from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse
from faker import Faker
from ninja.errors import ValidationError
from pytest_mock import MockerFixture

from app.core.models import (
    GlobalRole,
    GlobalRoleAssignment,
    User,
)
from app.verikit.services import EmailVerificationService


@pytest.fixture
def mock_validate_password(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("app.core.api.user.create.validate_password_for_user")


@pytest.mark.django_db
class TestCreateRegistration:
    path = reverse("api-1.0.0:create-registration")

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        mock_cf_turnstile: MagicMock,
        mock_validate_password: MagicMock,
        managed: bool,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        email_token = EmailVerificationService.issue_token(email)
        password = faker.password()

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": email_token,
                "password": password,
                "managed": managed,  # Should be ignored.
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["user"]["username"] == username
        assert data["user"]["email"] == email
        assert data["user"]["managed"] is False
        assert "uid" in data["user"]
        assert "password" not in data["user"]

        mock_validate_password.assert_called_once()
        mock_cf_turnstile.assert_called_once()

        user = User.objects.get(username=username)
        assert user.email == email
        assert user.check_password(password)
        assert not user.managed
        assert user.is_active

        assert get_user(api_client) == user

    def test_duplicate_username(
        self,
        faker: Faker,
        api_client: Client,
        mock_cf_turnstile: MagicMock,  # noqa: ARG002
        mock_validate_password: MagicMock,  # noqa: ARG002
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        email = faker.email()
        email_token = EmailVerificationService.issue_token(email)

        response = api_client.post(
            self.path,
            data={
                "username": existing_user.username,
                "email": email_token,
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        assert User.objects.filter(email=email).count() == 0

    def test_duplicate_email(
        self,
        faker: Faker,
        api_client: Client,
        mock_cf_turnstile: MagicMock,  # noqa: ARG002
        mock_validate_password: MagicMock,  # noqa: ARG002
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        username = faker.user_name()
        email_token = EmailVerificationService.issue_token(existing_user.email)

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": email_token,
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        assert User.objects.filter(username=username).count() == 0

    def test_password_validation_error(
        self,
        faker: Faker,
        api_client: Client,
        mock_cf_turnstile: MagicMock,  # noqa: ARG002
        mock_validate_password: MagicMock,
    ) -> None:
        email_token = EmailVerificationService.issue_token(faker.email())
        mock_validate_password.side_effect = ValidationError(
            errors=[
                {
                    "type": "value_error",
                    "loc": ["body", "payload", "password"],
                    "msg": "This password is too short.",
                }
            ]
        )

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "email": email_token,
                "password": "weak",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["details"][0]["msg"] == "This password is too short."

        assert not User.objects.exists()

    def test_cf_turnstile_enforced(
        self,
        settings: LazySettings,
        api_client: Client,
    ) -> None:
        response = api_client.post(self.path, data={"bad": "data"})
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert settings.CF_TURNSTILE_RESPONSE_HEADER_NAME in response.json()["message"]

    def test_email_case_insensitive(
        self,
        faker: Faker,
        api_client: Client,
        mock_cf_turnstile: MagicMock,  # noqa: ARG002
        mock_validate_password: MagicMock,  # noqa: ARG002
    ) -> None:
        username = faker.user_name()
        email = faker.email().lower()
        email_token = EmailVerificationService.issue_token(email.upper())
        password = faker.password()

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": email_token,
                "password": password,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        user = User.objects.get(username=username)
        assert user.email == email


@pytest.mark.django_db
class TestCreateUser:
    path = reverse("api-1.0.0:create-user")

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        mock_validate_password: MagicMock,
        managed: bool,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": email,
                "password": password,
                "managed": managed,
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["username"] == username
        assert data["email"] == email
        assert data["managed"] is managed
        assert "uid" in data
        assert "password" not in data

        mock_validate_password.assert_called_once()

        user = User.objects.get(username=username)
        assert user.email == email
        assert user.check_password(password)
        assert user.managed is managed
        assert user.is_active

    def test_duplicate_username(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        mock_validate_password: MagicMock,  # noqa: ARG002
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        email = faker.email()
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={
                "username": existing_user.username,
                "email": email,
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        assert User.objects.filter(email=email).count() == 0

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        mock_validate_password: MagicMock,  # noqa: ARG002
    ) -> None:
        unauthorized_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(unauthorized_user)

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "email": faker.email(),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

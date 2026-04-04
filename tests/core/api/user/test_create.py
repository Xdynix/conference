from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.core.models import User
from app.core.services import ApiKeyService, UserService
from app.core.services.user import InvalidPassword, UserIdentityConflict
from app.verikit.services import EmailVerificationService
from tests.helpers import any_str


@pytest.fixture
def user_service_create(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(UserService, "create_user")


@pytest.mark.django_db
class TestCreateAccount:
    path = reverse("api-1.0.0:create-account")

    @pytest.fixture(autouse=True)
    def mock_cf_turnstile(self, mock_cf_turnstile: MagicMock) -> MagicMock:
        return mock_cf_turnstile

    def test_happy_path(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": EmailVerificationService.issue_token(email),
                "password": password,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["user"]["uid"] == any_str
        assert data["user"]["username"] == username
        assert data["user"]["email"] == email
        assert data["user"]["managed"] is False
        assert data["user"]["roles"] == []

        user_service_create.assert_called_once_with(
            username=username,
            email=email,
            password=password,
            managed=False,
            payload=mocker.ANY,
        )
        logged_in_user = get_user(api_client)
        assert logged_in_user.username == username

    def test_trims_username(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()

        response = api_client.post(
            self.path,
            data={
                "username": f"  {username}  ",
                "email": EmailVerificationService.issue_token(email),
                "password": password,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["user"]["username"] == username

        user_service_create.assert_called_once_with(
            username=username,
            email=email,
            password=password,
            managed=False,
            payload=mocker.ANY,
        )

    def test_ignores_managed_field_in_payload(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": EmailVerificationService.issue_token(email),
                "password": password,
                "managed": True,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        user_service_create.assert_called_once_with(
            username=username,
            email=email,
            password=password,
            managed=False,
            payload=mocker.ANY,
        )

    def test_handle_user_identity_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        user_service_create.side_effect = UserIdentityConflict

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "email": EmailVerificationService.issue_token(faker.email()),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "username or email already exists" in response.json()["message"]

        user_service_create.assert_called_once()

    def test_rejects_whitespace_only_username(
        self,
        api_client: Client,
        faker: Faker,
    ) -> None:
        response = api_client.post(
            self.path,
            data={
                "username": "   ",
                "email": EmailVerificationService.issue_token(faker.email()),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "username"]
        assert "at least 1 character" in error["msg"]

    def test_handle_invalid_password(
        self,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        user_service_create.side_effect = InvalidPassword(
            [
                "This password is too short.",
                "This password is too common.",
            ]
        )

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "email": EmailVerificationService.issue_token(faker.email()),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error1, error2] = data["details"]
        assert error1["type"] == "value_error"
        assert error1["loc"] == ["body", "payload", "password"]
        assert "too short" in error1["msg"]
        assert error2["type"] == "value_error"
        assert error2["loc"] == ["body", "payload", "password"]
        assert "too common" in error2["msg"]

        user_service_create.assert_called_once()

    def test_bearer_auth_rejected(
        self,
        api_client: Client,
        faker: Faker,
        user_service_create: MagicMock,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        _, plaintext = ApiKeyService.create_key(user)

        response = api_client.post(
            self.path,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "API key" in response.json()["message"]

        user_service_create.assert_not_called()


@pytest.mark.django_db
class TestCreateUser:
    path = reverse("api-1.0.0:create-user")

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
        admin_user: User,
        managed: bool,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()
        api_client.force_login(admin_user)

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
        assert data["uid"] == any_str
        assert data["username"] == username
        assert data["email"] == email
        assert data["managed"] == managed
        assert data["roles"] == []

        user_service_create.assert_called_once_with(
            username=username,
            email=email,
            password=password,
            managed=managed,
            payload=mocker.ANY,
        )

    def test_empty_email_allowed(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
        admin_user: User,
    ) -> None:
        username = faker.user_name()
        password = faker.password()
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path,
            data={
                "username": username,
                "email": "",
                "password": password,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        user_service_create.assert_called_once_with(
            username=username,
            email="",
            password=password,
            managed=False,
            payload=mocker.ANY,
        )

    def test_handle_user_identity_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
        admin_user: User,
    ) -> None:
        user_service_create.side_effect = UserIdentityConflict
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "username or email already exists" in response.json()["message"]

        user_service_create.assert_called_once()

    def test_handle_invalid_password(
        self,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
        admin_user: User,
    ) -> None:
        user_service_create.side_effect = InvalidPassword(
            [
                "This password is too short.",
                "This password is too common.",
            ]
        )
        api_client.force_login(admin_user)

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error1, error2] = data["details"]
        assert error1["type"] == "value_error"
        assert error1["loc"] == ["body", "payload", "password"]
        assert "too short" in error1["msg"]
        assert error2["type"] == "value_error"
        assert error2["loc"] == ["body", "payload", "password"]
        assert "too common" in error2["msg"]

        user_service_create.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user_service_create: MagicMock,
    ) -> None:
        regular_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(regular_user)

        response = api_client.post(
            self.path,
            data={
                "username": faker.user_name(),
                "email": faker.email(),
                "password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        user_service_create.assert_not_called()

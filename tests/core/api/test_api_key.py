from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.core.models import ApiKey, User
from app.core.services.api_key import ApiKeyService
from tests.helpers import any_str


@pytest.fixture
def user_password(faker: Faker) -> str:
    return faker.password()


@pytest.fixture
def user(faker: Faker, user_password: str) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        password=user_password,
        email=faker.email(),
    )


@pytest.fixture
def api_key(user: User) -> ApiKey:
    api_key, _ = ApiKeyService.create_key(user)
    return api_key


@pytest.mark.django_db
class TestCreateApiKey:
    path = reverse("api-1.0.0:create-api-key")

    @pytest.fixture
    def api_key_service_create(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(ApiKeyService, "create_key")

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        user_password: str,
        api_key_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path, data={"password": user_password})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == {
            "key": any_str,
            "create_time": any_str,
        }
        assert data["key"].startswith(ApiKey.KEY_PREFIX)

        api_key_service_create.assert_called_once_with(user)

    def test_invalid_password(
        self,
        api_client: Client,
        user: User,
        api_key_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path, data={"password": "wrong"})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "password"]
        assert "Invalid password" in error["msg"]

        api_key_service_create.assert_not_called()

    def test_unauthenticated(
        self,
        api_client: Client,
        api_key_service_create: MagicMock,
    ) -> None:
        response = api_client.post(self.path, data={"password": "any"})
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        api_key_service_create.assert_not_called()


@pytest.mark.django_db
class TestGetCurrentApiKey:
    path = reverse("api-1.0.0:get-current-api-key")

    @pytest.fixture
    def api_key_service_get(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(ApiKeyService, "get_current_key")

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        api_key: ApiKey,  # noqa: ARG002
        api_key_service_get: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"create_time": any_str}

        api_key_service_get.assert_called_once_with(user)

    def test_no_active_key(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_excludes_plaintext(
        self,
        api_client: Client,
        user: User,
        api_key: ApiKey,  # noqa: ARG002
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path)

        data = response.json()
        assert "key" not in data
        assert "hashed_key" not in data

    def test_unauthenticated(
        self,
        api_client: Client,
        api_key_service_get: MagicMock,
    ) -> None:
        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        api_key_service_get.assert_not_called()


@pytest.mark.django_db
class TestDeleteCurrentApiKey:
    path = reverse("api-1.0.0:delete-current-api-key")

    @pytest.fixture
    def api_key_service_revoke(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(ApiKeyService, "revoke_key")

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        api_key: ApiKey,  # noqa: ARG002
        api_key_service_revoke: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path)
        assert response.status_code == HTTPStatus.NO_CONTENT

        api_key_service_revoke.assert_called_once_with(user)

    def test_no_active_key(
        self,
        api_client: Client,
        user: User,
        api_key_service_revoke: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path)
        assert response.status_code == HTTPStatus.NO_CONTENT

        api_key_service_revoke.assert_called_once_with(user)

    def test_unauthenticated(
        self,
        api_client: Client,
        api_key_service_revoke: MagicMock,
    ) -> None:
        response = api_client.delete(self.path)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        api_key_service_revoke.assert_not_called()


@pytest.mark.django_db
class TestApiKeyE2E:
    create_path = reverse("api-1.0.0:create-api-key")
    get_path = reverse("api-1.0.0:get-current-api-key")
    revoke_path = reverse("api-1.0.0:delete-current-api-key")

    def test_lifecycle(
        self,
        api_client: Client,
        user: User,
        user_password: str,
    ) -> None:
        api_client.force_login(user)

        # Create an API key via session auth.
        response = api_client.post(self.create_path, data={"password": user_password})
        assert response.status_code == HTTPStatus.OK
        plaintext = response.json()["key"]
        assert plaintext.startswith(ApiKey.KEY_PREFIX)

        # Use the key via bearer auth to access an authenticated endpoint.
        api_client.logout()
        bearer = {"Authorization": f"Bearer {plaintext}"}

        response = api_client.get(self.get_path, headers=bearer)
        assert response.status_code == HTTPStatus.OK
        assert response.json()["last_use_time"] is not None

        # Revoke the key.
        response = api_client.delete(self.revoke_path, headers=bearer)
        assert response.status_code == HTTPStatus.NO_CONTENT

        # Revoked key no longer authenticates.
        response = api_client.get(self.get_path, headers=bearer)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_rotation(
        self,
        api_client: Client,
        user: User,
        user_password: str,
    ) -> None:
        api_client.force_login(user)

        # Create the first key.
        response = api_client.post(self.create_path, data={"password": user_password})
        assert response.status_code == HTTPStatus.OK
        old_plaintext = response.json()["key"]

        # Rotate: creating a new key revokes the old one.
        response = api_client.post(self.create_path, data={"password": user_password})
        assert response.status_code == HTTPStatus.OK
        new_plaintext = response.json()["key"]
        assert new_plaintext != old_plaintext

        # Old key no longer authenticates.
        response = api_client.get(
            self.get_path,
            headers={"Authorization": f"Bearer {old_plaintext}"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        # New key works.
        response = api_client.get(
            self.get_path,
            headers={"Authorization": f"Bearer {new_plaintext}"},
        )
        assert response.status_code == HTTPStatus.OK

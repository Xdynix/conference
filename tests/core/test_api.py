from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse
from faker import Faker
from pydantic import BaseModel, JsonValue

from app.core.models import User


class UserCredentials(BaseModel):
    username: str
    password: str


@pytest.fixture
def user_credentials(faker: Faker) -> UserCredentials:
    return UserCredentials(username=faker.user_name(), password=faker.password())


@pytest.fixture
def user(faker: Faker, user_credentials: UserCredentials) -> User:
    return User.objects.create_user(
        **user_credentials.model_dump(),
        email=faker.email(),
        first_name=faker.first_name(),
        last_name=faker.last_name(),
    )


@pytest.fixture
def user_serialized(user: User) -> JsonValue:
    return {
        "uid": str(user.uid),
        "username": user.username,
        "email": user.email,
        "given_name": user.given_name,
        "family_name": user.family_name,
    }


@pytest.fixture
def authenticated_session(user_serialized: JsonValue) -> JsonValue:
    return {"user": user_serialized}


@pytest.mark.django_db
class TestGetSession:
    path = reverse("api-1.0.0:get-session")

    def test_authenticated(
        self,
        settings: LazySettings,
        api_client: Client,
        user: User,
        authenticated_session: JsonValue,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == authenticated_session

        assert settings.CSRF_COOKIE_NAME in api_client.cookies
        assert "no-cache" in response.headers["Cache-Control"]

    def test_unauthenticated(self, api_client: Client) -> None:
        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}


@pytest.mark.django_db
class TestCreateSession:
    path = reverse("api-1.0.0:create-session")

    @pytest.fixture
    def invalid_credentials(self, faker: Faker) -> UserCredentials:
        return UserCredentials(
            username=faker.user_name(),
            password=faker.password(),
        )

    def test_valid_credentials(
        self,
        api_client: Client,
        user: User,
        user_credentials: UserCredentials,
        authenticated_session: JsonValue,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        assert not get_user(api_client).is_authenticated

        response = api_client.post(self.path, data=user_credentials.model_dump())
        assert response.status_code == HTTPStatus.OK
        assert response.json() == authenticated_session

        assert get_user(api_client) == user
        mock_cf_turnstile.assert_called_once()

    def test_invalid_credentials(
        self,
        api_client: Client,
        invalid_credentials: UserCredentials,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        assert not get_user(api_client).is_authenticated

        response = api_client.post(self.path, data=invalid_credentials.model_dump())
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {"message": "Invalid credentials."}

        assert not get_user(api_client).is_authenticated
        mock_cf_turnstile.assert_called_once()

    def test_cf_turnstile_enforced(
        self,
        settings: LazySettings,
        api_client: Client,
    ) -> None:
        assert not get_user(api_client).is_authenticated

        response = api_client.post(self.path, data={"bad": "data"})
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert settings.CF_TURNSTILE_RESPONSE_HEADER_NAME in response.json()["message"]

        assert not get_user(api_client).is_authenticated

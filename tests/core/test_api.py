from http import HTTPStatus

import pytest
from django.conf import LazySettings
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

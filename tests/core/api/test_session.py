from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse
from faker import Faker
from pydantic import BaseModel, JsonValue

from app.core.models import User
from app.core.schemas import Session
from tests.helpers import update_object


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


@pytest.mark.django_db
class TestDeleteSession:
    path = reverse("api-1.0.0:delete-session")

    def test_authenticated(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

        assert not get_user(api_client).is_authenticated

    def test_unauthenticated(self, api_client: Client) -> None:
        response = api_client.delete(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

        assert not get_user(api_client).is_authenticated


@pytest.fixture
def impersonator(faker: Faker) -> User:
    return User.objects.create_superuser(username=faker.user_name())


@pytest.fixture
def impersonated(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.mark.django_db
class TestAssumeSession:
    path = reverse("api-1.0.0:assume-session")

    def test_happy_path(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
    ) -> None:
        api_client.force_login(impersonator)

        response = api_client.post(
            self.path,
            data={"impersonated": impersonated.username},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["user"]["uid"] == str(impersonated.uid)
        assert data["impersonating"] is True

        assert get_user(api_client) == impersonated
        assert api_client.session[Session.Key.IMPERSONATOR_ID] == str(impersonator.id)

    def test_non_superuser(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
    ) -> None:
        update_object(impersonator, is_superuser=False)
        api_client.force_login(impersonator)

        response = api_client.post(
            self.path,
            data={"impersonated": impersonated.username},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert get_user(api_client) == impersonator
        assert Session.Key.IMPERSONATOR_ID not in api_client.session

    def test_unauthenticated(self, api_client: Client) -> None:
        response = api_client.post(self.path, data={"impersonated": "foobar"})
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert not get_user(api_client).is_authenticated

    def test_impersonated_not_exist(
        self,
        api_client: Client,
        impersonator: User,
    ) -> None:
        api_client.force_login(impersonator)

        response = api_client.post(
            self.path,
            data={"impersonated": "not-exist"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {"message": "Impersonated not found."}

        assert get_user(api_client) == impersonator

    @pytest.mark.parametrize(
        "impersonated_update",
        [
            {"is_active": False},
            {"is_superuser": True},
        ],
    )
    def test_impersonated_invalid(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
        impersonated_update: dict[str, Any],
    ) -> None:
        update_object(impersonated, **impersonated_update)
        api_client.force_login(impersonator)

        response = api_client.post(
            self.path,
            data={"impersonated": impersonated.username},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {"message": "Impersonated not found."}

        assert get_user(api_client) == impersonator


@pytest.mark.django_db
class TestRevertSession:
    path = reverse("api-1.0.0:revert-session")

    @classmethod
    def force_assume(cls, client: Client, user: User) -> None:
        session = client.session
        session[Session.Key.IMPERSONATOR_ID] = str(user.id)
        session.save()

    def test_happy_path(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
    ) -> None:
        api_client.force_login(impersonated)
        self.force_assume(api_client, impersonator)

        response = api_client.post(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["user"]["uid"] == str(impersonator.uid)
        assert "impersonating" not in data

        assert get_user(api_client) == impersonator
        assert Session.Key.IMPERSONATOR_ID not in api_client.session

    def test_not_impersonating(
        self,
        api_client: Client,
        impersonated: User,
    ) -> None:
        api_client.force_login(impersonated)

        response = api_client.post(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["user"]["uid"] == str(impersonated.uid)
        assert "impersonating" not in data

        assert get_user(api_client) == impersonated
        assert Session.Key.IMPERSONATOR_ID not in api_client.session

    def test_unauthenticated(self, api_client: Client) -> None:
        response = api_client.post(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

    def test_impersonator_not_exist(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
    ) -> None:
        api_client.force_login(impersonated)
        self.force_assume(api_client, impersonator)
        impersonator.delete()

        response = api_client.post(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

    def test_impersonator_inactive(
        self,
        api_client: Client,
        impersonator: User,
        impersonated: User,
    ) -> None:
        api_client.force_login(impersonated)
        self.force_assume(api_client, impersonator)
        update_object(impersonator, is_active=False)

        response = api_client.post(self.path)
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}


@pytest.mark.django_db
def test_impersonation_e2e(
    api_client: Client,
    impersonator: User,
    impersonated: User,
) -> None:
    api_client.force_login(impersonator)
    assert get_user(api_client) == impersonator

    response = api_client.post(
        reverse("api-1.0.0:assume-session"),
        data={"impersonated": impersonated.username},
    )
    assert response.status_code == HTTPStatus.OK
    assert get_user(api_client) == impersonated

    response = api_client.post(reverse("api-1.0.0:revert-session"))
    assert response.status_code == HTTPStatus.OK
    assert get_user(api_client) == impersonator

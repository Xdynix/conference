from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.core.models import (
    GlobalRole,
    GlobalRoleAssignment,
    User,
)
from tests.helpers import update_object


@pytest.mark.django_db
class TestGetCurrentUser:
    path = reverse("api-1.0.0:get-current-user")

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(user.uid)
        assert data["username"] == user.username
        assert data["email"] == user.email
        assert data["managed"] == user.managed

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
    ) -> None:
        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestGetUser:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:get-user", args=[user_id])

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.get(self.path(user_id=user.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(user.uid)
        assert data["username"] == user.username
        assert data["email"] == user.email
        assert data["managed"] == user.managed

    def test_inactive_user_not_found(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(authorized_user)

        response = api_client.get(self.path(user_id=user.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_nonexistent_user_not_found(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.get(self.path(user_id=ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        another_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(another_user)

        response = api_client.get(self.path(user_id=user.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        response = api_client.get(self.path(user_id=user.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

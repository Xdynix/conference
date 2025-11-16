from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestUpdateUserRoles:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user-roles", args=[user_id])

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
        return user

    def test_happy_path(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(user.uid)
        assert data["roles"] == [GlobalRole.ADMIN]

        roles = list(
            GlobalRoleAssignment.objects.filter(user=user)
            .order_by("role")
            .values_list("role", flat=True)
        )
        assert roles == [GlobalRole.ADMIN]

    def test_remove_all_roles(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": []},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["roles"] == []
        assert not GlobalRoleAssignment.objects.filter(user=user).exists()

    def test_inactive_user_not_found(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_nonexistent_user_not_found(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=ULID()),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        unauthorized_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(unauthorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        response = api_client.put(
            self.path(user_id=user.uid),
            data={"roles": [GlobalRole.ADMIN]},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

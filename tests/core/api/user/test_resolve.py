from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.core.models import Permission, Role, RoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestResolveUser:
    path = reverse("api-1.0.0:resolve-user")

    @pytest.fixture
    def reader_role(self) -> Role:
        permission, _ = Permission.objects.get_or_create(key=User.READ)
        role = Role.objects.create(name="reader", display_name="Reader")
        role.permissions.add(permission)
        return role

    @pytest.fixture
    def authorized_user(self, faker: Faker, reader_role: Role) -> User:
        user = User.objects.create_user(username=faker.user_name())
        RoleAssignment.objects.create(user=user, role=reader_role)
        return user

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_resolve_by_username_found(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "username", "username": user.username},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"uid": str(user.uid)}

    def test_resolve_by_email_found(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "email", "email": user.email},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"uid": str(user.uid)}

    def test_resolve_by_email_case_insensitive(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "email", "email": user.email.upper()},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"uid": str(user.uid)}

    def test_resolve_by_username_not_found(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "username", "username": "nonexistent"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

    def test_resolve_by_email_not_found(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "email", "email": "nonexistent@example.com"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

    def test_resolve_inactive_user_not_found(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(authorized_user)

        response = api_client.post(
            self.path,
            data={"by": "username", "username": user.username},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={"by": "username", "username": "someuser"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_forbidden(
        self,
        api_client: Client,
    ) -> None:
        response = api_client.post(
            self.path,
            data={"by": "username", "username": "someuser"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestListUsers:
    path = reverse("api-1.0.0:list-users")

    @pytest.fixture
    def users(self) -> list[User]:
        users = [
            User.objects.create_user(
                username=f"user{i}",
                email=f"user{i}@example.com",
            )
            for i in range(5)
        ]
        GlobalRoleAssignment.objects.create(user=users[0], role=GlobalRole.ADMIN)
        GlobalRoleAssignment.objects.create(user=users[1], role=GlobalRole.READ_ALL)
        return users

    def test_happy_path(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= len(users)

    def test_filter_by_username(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        target_user = users[0]
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"username": target_user.username})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [item] = data["items"]
        assert item["username"] == target_user.username

    def test_filter_by_email(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        target_user = users[0]
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"email": target_user.email})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [item] = data["items"]
        assert item["email"] == target_user.email

    def test_filter_by_email_case_insensitive(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        target_user = users[0]
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"email": target_user.email.upper()})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [item] = data["items"]
        assert item["email"] == target_user.email

    def test_filter_by_search_username(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        target_user = users[0]
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"search": target_user.username})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [item] = data["items"]
        assert item["username"] == target_user.username

    def test_filter_by_search_email(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        target_user = users[1]
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"search": target_user.email})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [item] = data["items"]
        assert item["email"] == target_user.email

    @pytest.mark.parametrize("managed", [True, False])
    def test_filter_by_managed(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
        managed: bool,
    ) -> None:
        managed_user = users[0]
        update_object(managed_user, managed=managed)
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"managed": managed})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        response_items = data["items"]
        managed_statuses = [item["managed"] for item in response_items]
        assert all(status is managed for status in managed_statuses)
        user_uids = {item["uid"] for item in response_items}
        assert str(managed_user.uid) in user_uids

    def test_excludes_inactive_users(
        self,
        api_client: Client,
        admin_user: User,
        users: list[User],
    ) -> None:
        inactive_user = users[0]
        update_object(inactive_user, is_active=False)
        api_client.force_login(admin_user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        user_uids = {item["uid"] for item in data["items"]}
        assert str(inactive_user.uid) not in user_uids

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
    ) -> None:
        response = api_client.get(self.path)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_empty_result_with_nonexistent_filter(
        self,
        api_client: Client,
        admin_user: User,
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.get(self.path, {"username": "nonexistent"})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["items"] == []

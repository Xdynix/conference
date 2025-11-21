from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.services import UserService
from app.core.services.user import UserIdentityConflict
from app.verikit.services import EmailVerificationService
from tests.helpers import any_str, update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


@pytest.fixture
def user_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(UserService, "update_user")


@pytest.mark.django_db
class TestUpdateCurrentUser:
    path = reverse("api-1.0.0:update-current-user")

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
    ) -> None:
        new_username = faker.user_name()
        new_email = faker.email()
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={
                "username": new_username,
                "email": EmailVerificationService.issue_token(new_email),
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == any_str
        assert data["username"] == new_username
        assert data["email"] == new_email

        user_service_update.assert_called_once_with(
            user=user,
            username=new_username,
            email=new_email,
        )

    def test_managed_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
    ) -> None:
        update_object(user, managed=True)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Managed users" in response.json()["message"]

        user_service_update.assert_not_called()

    def test_handle_user_identity_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
    ) -> None:
        user_service_update.side_effect = UserIdentityConflict
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "username or email already exists" in response.json()["message"]

        user_service_update.assert_called_once()

    def test_unauthenticated_user_unauthorized(
        self,
        faker: Faker,
        api_client: Client,
        user_service_update: MagicMock,
    ) -> None:
        response = api_client.patch(
            self.path,
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        user_service_update.assert_not_called()


@pytest.mark.django_db
class TestUpdateUser:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user", args=[user_id])

    @pytest.fixture
    def admin_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
        admin_user: User,
        managed: bool,
    ) -> None:
        update_object(user, managed=managed)
        new_username = faker.user_name()
        new_email = faker.email()
        api_client.force_login(admin_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={
                "username": new_username,
                "email": new_email,
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == any_str
        assert data["username"] == new_username
        assert data["email"] == new_email

        user_service_update.assert_called_once_with(
            user=user,
            username=new_username,
            email=new_email,
        )

    def test_update_inactive_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
        admin_user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(admin_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update.assert_not_called()

    def test_update_superuser_not_found(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
        admin_user: User,
    ) -> None:
        update_object(user, is_superuser=True)
        api_client.force_login(admin_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update.assert_not_called()

    def test_nonexistent_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        user_service_update: MagicMock,
        admin_user: User,
    ) -> None:
        api_client.force_login(admin_user)

        response = api_client.patch(
            self.path(user_id=ULID()),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user_service_update.assert_not_called()

    def test_handle_user_identity_conflict(
        self,
        faker: Faker,
        api_client: Client,
        admin_user: User,
        user: User,
        user_service_update: MagicMock,
    ) -> None:
        user_service_update.side_effect = UserIdentityConflict
        api_client.force_login(admin_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "username or email already exists" in response.json()["message"]

        user_service_update.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        user_service_update: MagicMock,
    ) -> None:
        regular_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(regular_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        user_service_update.assert_not_called()

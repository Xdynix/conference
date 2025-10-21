from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import Permission, Role, RoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestResolveUser:
    path = reverse("api-1.0.0:resolve-user")

    @pytest.fixture
    def user_read_permission(self) -> Permission:
        return Permission.objects.get_or_create(key=User.READ)[0]

    @pytest.fixture
    def reader_role(self, user_read_permission: Permission) -> Role:
        role = Role.objects.create(name="reader", display_name="Reader")
        role.permissions.add(user_read_permission)
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


@pytest.mark.django_db(transaction=True)
class TestUpdateCurrentUser:
    path = reverse("api-1.0.0:update-current-user")

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    @pytest.fixture
    def mock_verify_token(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "app.verikit.services.EmailVerificationService.verify_token"
        )

    def test_update_username_only(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        original_email = user.email
        new_username = faker.user_name()
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": new_username},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == new_username
        assert user.email == original_email

    def test_update_email_only(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        original_username = user.username
        new_email = faker.email()
        email_token = faker.pystr()
        mock_verify_token.return_value = new_email
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == new_email
        mock_verify_token.assert_called_once_with(email_token)

    def test_update_both_username_and_email(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        new_username = faker.user_name()
        new_email = faker.email()
        email_token = faker.pystr()
        mock_verify_token.return_value = new_email
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": new_username, "email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == new_username
        assert user.email == new_email
        mock_verify_token.assert_called_once_with(email_token)

    def test_no_changes_when_username_same(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
    ) -> None:
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": user.username},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

    def test_no_changes_when_email_same(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        email_token = faker.pystr()
        mock_verify_token.return_value = user.email
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()
        mock_verify_token.assert_called_once_with(email_token)

    def test_email_comparison_case_insensitive(
        self,
        mocker: MockerFixture,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        email_token = faker.pystr()
        mock_verify_token.return_value = user.email.upper()
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()
        mock_verify_token.assert_called_once_with(email_token)

    def test_managed_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        update_object(user, managed=True)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Managed users" in response.json()["message"]

    def test_duplicate_username_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_username = user.username
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": existing_user.username},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username already exists" in response.json()["message"]

        # Verify the database was not modified.
        user.refresh_from_db()
        assert user.username == original_username

    def test_duplicate_email_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_email = user.email
        email_token = faker.pystr()
        mock_verify_token.return_value = existing_user.email
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "email already exists" in response.json()["message"]

        # Verify the database was not modified.
        user.refresh_from_db()
        assert user.email == original_email
        mock_verify_token.assert_called_once_with(email_token)

    def test_duplicate_username_and_email_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_verify_token: MagicMock,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_username = user.username
        original_email = user.email
        email_token = faker.pystr()
        mock_verify_token.return_value = existing_user.email
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": existing_user.username, "email": email_token},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        # Verify the database was not modified.
        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == original_email
        mock_verify_token.assert_called_once_with(email_token)

    def test_unauthenticated_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
    ) -> None:
        response = api_client.patch(
            self.path,
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db(transaction=True)
class TestUpdateUser:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user", args=[user_id])

    @pytest.fixture
    def user_admin_permission(self) -> Permission:
        return Permission.objects.get_or_create(key=User.ADMIN)[0]

    @pytest.fixture
    def admin_role(self, user_admin_permission: Permission) -> Role:
        role = Role.objects.create(name="admin", display_name="Admin")
        role.permissions.add(user_admin_permission)
        return role

    @pytest.fixture
    def authorized_user(self, faker: Faker, admin_role: Role) -> User:
        user = User.objects.create_user(username=faker.user_name())
        RoleAssignment.objects.create(user=user, role=admin_role)
        return user

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
        managed: bool,
    ) -> None:
        update_object(user, managed=managed)
        new_username = faker.user_name()
        new_email = faker.email()
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": new_username, "email": new_email},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == new_username
        assert user.email == new_email

    def test_update_username_only(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        original_email = user.email
        new_username = faker.user_name()
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": new_username},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == new_username
        assert user.email == original_email

    def test_update_email_only(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        original_username = user.username
        new_email = faker.email()
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"email": new_email},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == new_email

    def test_no_changes_when_username_same(
        self,
        mocker: MockerFixture,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": user.username},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

    def test_no_changes_when_email_same(
        self,
        mocker: MockerFixture,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"email": user.email},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

    def test_email_comparison_case_insensitive(
        self,
        mocker: MockerFixture,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"email": user.email.upper()},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

    def test_update_inactive_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        update_object(user, is_active=False)
        original_username = user.username
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.username == original_username

    def test_update_superuser_not_found(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        update_object(user, is_superuser=True)
        original_username = user.username
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.username == original_username

    def test_nonexistent_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=ULID()),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_duplicate_username_conflict(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_username = user.username
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": existing_user.username},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username already exists" in response.json()["message"]

        user.refresh_from_db()
        assert user.username == original_username

    def test_duplicate_email_conflict(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_email = user.email
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"email": existing_user.email},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "email already exists" in response.json()["message"]

        user.refresh_from_db()
        assert user.email == original_email

    def test_duplicate_username_and_email_conflict(
        self,
        faker: Faker,
        api_client: Client,
        authorized_user: User,
        user: User,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_username = user.username
        original_email = user.email
        api_client.force_login(authorized_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": existing_user.username, "email": existing_user.email},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == original_email

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        another_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(another_user)

        response = api_client.patch(
            self.path(user_id=user.uid),
            data={"username": faker.user_name()},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestUpdateCurrentUserPassword:
    path = reverse("api-1.0.0:update-current-user-password")

    @pytest.fixture
    def old_password(self) -> str:
        return "OldPassword123!"

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": old_password,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""

        user.refresh_from_db()
        assert user.check_password(new_password)
        assert not user.check_password(old_password)

        assert get_user(api_client) == user

    def test_invalid_old_password(
        self,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": "WrongPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert response_data["details"][0]["type"] == "value_error"
        assert response_data["details"][0]["loc"] == ["body", "payload", "old_password"]
        assert "Invalid old password" in response_data["details"][0]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_weak_new_password(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
        old_password: str,
    ) -> None:
        mock_validate = mocker.patch("app.core.api.user.validate_password")
        mock_validate.side_effect = DjangoValidationError(
            [
                "This password is too short. It must contain at least 8 characters.",
                "This password is too common.",
            ]
        )
        new_password = "weak"
        api_client.force_login(user)

        response = api_client.put(
            self.path,
            data={
                "old_password": old_password,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert len(response_data["details"]) == 2
        for error in response_data["details"]:
            assert error["type"] == "value_error"
            assert error["loc"] == ["body", "payload", "new_password"]
        assert "too short" in response_data["details"][0]["msg"]
        assert "too common" in response_data["details"][1]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

        mock_validate.assert_called_once_with(new_password, user=user)

    def test_unauthenticated_user_forbidden(self, api_client: Client) -> None:
        response = api_client.put(
            self.path,
            data={
                "old_password": "OldPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUpdateUserPassword:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-user-password", args=[user_id])

    @pytest.fixture
    def user_admin_permission(self) -> Permission:
        return Permission.objects.get_or_create(key=User.ADMIN)[0]

    @pytest.fixture
    def admin_role(self, user_admin_permission: Permission) -> Role:
        role = Role.objects.create(name="admin", display_name="Admin")
        role.permissions.add(user_admin_permission)
        return role

    @pytest.fixture
    def authorized_user(self, faker: Faker, admin_role: Role) -> User:
        user = User.objects.create_user(username=faker.user_name())
        RoleAssignment.objects.create(user=user, role=admin_role)
        return user

    @pytest.fixture
    def old_password(self) -> str:
        return "OldPassword123!"

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    def test_happy_path(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        new_password = "NewPassword456!"
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": new_password},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""

        user.refresh_from_db()
        assert user.check_password(new_password)
        assert not user.check_password(old_password)

    def test_change_inactive_user_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_change_superuser_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        update_object(user, is_superuser=True)
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        user.refresh_from_db()
        assert user.check_password(old_password)

    def test_nonexistent_user_forbidden(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=ULID()),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_weak_new_password(
        self,
        mocker: MockerFixture,
        api_client: Client,
        authorized_user: User,
        user: User,
        old_password: str,
    ) -> None:
        mock_validate = mocker.patch("app.core.api.user.validate_password")
        mock_validate.side_effect = DjangoValidationError(
            [
                "This password is too short. It must contain at least 8 characters.",
                "This password is too common.",
            ]
        )
        new_password = "weak"
        api_client.force_login(authorized_user)

        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": new_password},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response_data = response.json()
        assert len(response_data["details"]) == 2
        for error in response_data["details"]:
            assert error["type"] == "value_error"
            assert error["loc"] == ["body", "payload", "new_password"]
        assert "too short" in response_data["details"][0]["msg"]
        assert "too common" in response_data["details"][1]["msg"]

        user.refresh_from_db()
        assert user.check_password(old_password)

        mock_validate.assert_called_once()

    def test_unauthorized_user_forbidden(self, api_client: Client, user: User) -> None:
        response = api_client.put(
            self.path(user_id=user.uid),
            data={"new_password": "NewPassword456!"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

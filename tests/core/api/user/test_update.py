from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import (
    GlobalRole,
    GlobalRoleAssignment,
    User,
)
from app.verikit.services import EmailVerificationService
from tests.helpers import update_object


@pytest.mark.django_db(transaction=True)
class TestUpdateCurrentUser:
    path = reverse("api-1.0.0:update-current-user")

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
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
    ) -> None:
        original_username = user.username
        new_email = faker.email()
        email_token = EmailVerificationService.issue_token(new_email)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == new_email

    def test_update_both_username_and_email(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        new_username = faker.user_name()
        new_email = faker.email()
        email_token = EmailVerificationService.issue_token(new_email)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": new_username, "email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        user.refresh_from_db()
        assert user.username == new_username
        assert user.email == new_email

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
        api_client: Client,
        user: User,
    ) -> None:
        email_token = EmailVerificationService.issue_token(user.email)
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

    def test_email_comparison_case_insensitive(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
    ) -> None:
        email_token = EmailVerificationService.issue_token(user.email.upper())
        mock_save = mocker.spy(User, "asave")
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.OK

        mock_save.assert_not_called()

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

        user.refresh_from_db()
        assert user.username == original_username

    def test_duplicate_email_conflict(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_email = user.email
        email_token = EmailVerificationService.issue_token(existing_user.email)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"email": email_token},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "email already exists" in response.json()["message"]

        user.refresh_from_db()
        assert user.email == original_email

    def test_duplicate_username_and_email_conflict(
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
        original_email = user.email
        email_token = EmailVerificationService.issue_token(existing_user.email)
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={"username": existing_user.username, "email": email_token},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "username or email already exists" in response.json()["message"]

        user.refresh_from_db()
        assert user.username == original_username
        assert user.email == original_email

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

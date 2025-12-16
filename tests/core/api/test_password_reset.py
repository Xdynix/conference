from datetime import timedelta
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.core.models import PasswordResetToken, User
from app.core.services import PasswordResetService
from app.core.types import Password
from app.utils.email import EmailFormatName, EmailTemplate
from tests.helpers import any_str, update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        password=faker.password(),
        email=faker.email(),
    )


@pytest.mark.django_db
class TestCreatePasswordReset:
    path = reverse("api-1.0.0:create-password-reset")

    @pytest.fixture
    def mock_create_token(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "app.core.api.password_reset.PasswordResetService.create_token"
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        mock_create_token: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        mock_create_token.return_value = PasswordResetToken()

        response = api_client.post(self.path, data={"email": user.email})

        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {}

        mock_create_token.assert_called_once_with(
            user,
            password_reset_page_url=any_str,
        )
        mock_cf_turnstile.assert_called_once()

    def test_inactive_user(
        self,
        api_client: Client,
        user: User,
        mock_create_token: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        update_object(user, is_active=False)

        response = api_client.post(self.path, data={"email": user.email})
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {}

        mock_create_token.assert_not_called()
        mock_cf_turnstile.assert_called_once()

    def test_not_exist_user(
        self,
        faker: Faker,
        api_client: Client,
        mock_create_token: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        response = api_client.post(self.path, data={"email": faker.email()})
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {}

        mock_create_token.assert_not_called()
        mock_cf_turnstile.assert_called_once()

    def test_user_without_usable_password(
        self,
        api_client: Client,
        user: User,
        mock_create_token: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        user.set_unusable_password()
        user.save()

        response = api_client.post(self.path, data={"email": user.email})
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {}

        mock_create_token.assert_not_called()
        mock_cf_turnstile.assert_called_once()

    def test_rate_limiting(
        self,
        settings: LazySettings,
        api_client: Client,
        user: User,
        mock_create_token: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        mock_create_token.return_value = None
        settings.PASSWORD_RESET_TOKEN_INTERVAL = timedelta(seconds=42)

        response = api_client.post(self.path, data={"email": user.email})
        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS

        data = response.json()
        assert "password reset token was recently issued" in data["message"]
        assert response.headers["Retry-After"] == "42"

        mock_create_token.assert_called_once_with(
            user,
            password_reset_page_url=any_str,
        )
        mock_cf_turnstile.assert_called_once()

    def test_cf_turnstile_enforced(
        self,
        settings: LazySettings,
        api_client: Client,
    ) -> None:
        response = api_client.post(self.path, data={"bad": "data"})

        assert response.status_code == HTTPStatus.FORBIDDEN

        assert settings.CF_TURNSTILE_RESPONSE_HEADER_NAME in response.json()["message"]


@pytest.mark.django_db
class TestConsumePasswordReset:
    path = reverse("api-1.0.0:consume-password-reset")

    @pytest.fixture
    def mock_consume_token(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "app.core.api.password_reset.PasswordResetService.consume_token"
        )

    @pytest.fixture
    def mock_validate_password(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.core.api.password_reset.validate_password")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_consume_token: MagicMock,
        mock_validate_password: MagicMock,
    ) -> None:
        token = faker.pystr()
        new_password = faker.password()
        mock_consume_token.return_value = True

        response = api_client.post(
            self.path,
            data={
                "user": str(user.uid),
                "token": token,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        mock_validate_password.assert_called_once_with(new_password, user=user)
        mock_consume_token.assert_called_once_with(user, token, Password(new_password))

    def test_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        mock_consume_token: MagicMock,
        mock_validate_password: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path,
            data={
                "user": str(ULID()),
                "token": faker.pystr(),
                "new_password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        data = response.json()
        assert data["message"] == "Invalid or expired password reset token."

        mock_validate_password.assert_not_called()
        mock_consume_token.assert_not_called()

    def test_invalid_or_expired_token(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_consume_token: MagicMock,
        mock_validate_password: MagicMock,
    ) -> None:
        token = faker.pystr()
        new_password = faker.password()
        mock_consume_token.return_value = False

        response = api_client.post(
            self.path,
            data={
                "user": str(user.uid),
                "token": token,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        data = response.json()
        assert data["message"] == "Invalid or expired password reset token."

        mock_validate_password.assert_called_once_with(new_password, user=user)
        mock_consume_token.assert_called_once_with(user, token, Password(new_password))

    def test_invalid_new_password(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        mock_consume_token: MagicMock,
        mock_validate_password: MagicMock,
    ) -> None:
        token = faker.pystr()
        new_password = faker.password()
        mock_validate_password.side_effect = ValidationError(
            ["This password is too short."]
        )
        mock_consume_token.return_value = True

        response = api_client.post(
            self.path,
            data={
                "user": str(user.uid),
                "token": token,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["msg"] == "This password is too short."

        mock_validate_password.assert_called_once_with(new_password, user=user)
        mock_consume_token.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestPasswordResetE2E:
    create_path = reverse("api-1.0.0:create-password-reset")
    consume_path = reverse("api-1.0.0:consume-password-reset")

    @pytest.fixture(autouse=True)
    def mock_token_interval(self, settings: LazySettings) -> None:
        settings.PASSWORD_RESET_TOKEN_INTERVAL = timedelta(seconds=60)

    @pytest.fixture(autouse=True)
    def mock_template(self, mocker: MockerFixture) -> None:
        mocker.patch.object(
            PasswordResetService,
            "password_reset_email_template",
            EmailTemplate(
                format=EmailFormatName.TEXT,
                subject="Password Reset",
                body="Link: {{ reset_url }}",
            ),
        )

    @pytest.fixture(autouse=True)
    def mock_cf_turnstile(self, mock_cf_turnstile: MagicMock) -> MagicMock:
        return mock_cf_turnstile

    def test_complete_flow_happy_path(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        old_password = faker.password()
        new_password = faker.password()
        email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=email,
            password=old_password,
        )

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        [sent_email] = mailoutbox
        assert sent_email.to == [email]

        email_body = sent_email.body
        fragment = email_body.split("#")[-1]
        user_id_str, token = fragment.split(":")

        response = api_client.post(
            self.consume_path,
            data={
                "user": user_id_str,
                "token": token.strip(),
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        user.refresh_from_db()
        assert not user.check_password(old_password)
        assert user.check_password(new_password)

    def test_wrong_token_blocks_flow(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        old_password = faker.password()
        new_password = faker.password()
        email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=email,
            password=old_password,
        )
        wrong_token = "wrong_token_123"

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        fragment = sent_email.body.split("#")[-1]
        user_id_str, correct_token = fragment.split(":")
        assert wrong_token != correct_token

        response = api_client.post(
            self.consume_path,
            data={
                "user": user_id_str,
                "token": wrong_token,
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data["message"] == "Invalid or expired password reset token."

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

    def test_expired_token_blocks_flow(
        self,
        faker: Faker,
        settings: LazySettings,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        old_password = faker.password()
        new_password = faker.password()
        email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=email,
            password=old_password,
        )
        settings.PASSWORD_RESET_TOKEN_EXPIRY = timedelta(seconds=-1)

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        fragment = sent_email.body.split("#")[-1]
        user_id_str, token = fragment.split(":")

        response = api_client.post(
            self.consume_path,
            data={
                "user": user_id_str,
                "token": token.strip(),
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data["message"] == "Invalid or expired password reset token."

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

    def test_rate_limiting_blocks_multiple_requests(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email()
        User.objects.create_user(
            username=faker.user_name(),
            password=faker.password(),
            email=email,
        )

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED
        assert len(mailoutbox) == 1

        # Rate limiting should have prevented a second email.
        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        data = response.json()
        assert "password reset token was recently issued" in data["message"]
        assert len(mailoutbox) == 1

    def test_used_token_cannot_be_reused(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        old_password = faker.password()
        new_password = faker.password()
        email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=email,
            password=old_password,
        )

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        fragment = sent_email.body.split("#")[-1]
        user_id_str, token = fragment.split(":")

        response = api_client.post(
            self.consume_path,
            data={
                "user": user_id_str,
                "token": token.strip(),
                "new_password": new_password,
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        response = api_client.post(
            self.consume_path,
            data={
                "user": user_id_str,
                "token": token.strip(),
                "new_password": faker.password(),
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data["message"] == "Invalid or expired password reset token."

        user.refresh_from_db()
        assert not user.check_password(old_password)
        assert user.check_password(new_password)

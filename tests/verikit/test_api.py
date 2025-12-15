from datetime import timedelta
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.utils.email import EmailFormatName, EmailTemplate
from app.verikit.models import EmailVerification
from app.verikit.services import EmailVerificationService


class TestCreateEmailVerification:
    path = reverse("api-1.0.0:create-email-verification")

    @pytest.fixture
    def mock_issue_code(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.verikit.api.EmailVerificationService.issue_code")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        mock_issue_code: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        email = faker.email()
        mock_verification = EmailVerification(
            email=email,
            code_hash="hash",
            create_time=timezone.now(),
            expire_time=timezone.now() + timedelta(minutes=10),
        )
        mock_issue_code.return_value = mock_verification

        response = api_client.post(self.path, data={"email": email})

        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["email"] == email
        assert "create_time" in data
        assert "expire_time" in data

        mock_issue_code.assert_called_once_with(email)
        mock_cf_turnstile.assert_called_once()

    def test_rate_limiting(
        self,
        faker: Faker,
        settings: LazySettings,
        api_client: Client,
        mock_issue_code: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        email = faker.email()
        mock_issue_code.return_value = None
        settings.VERIKIT_EMAIL_CODE_INTERVAL = timedelta(seconds=42)

        response = api_client.post(self.path, data={"email": email})

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        data = response.json()
        assert "verification code was recently issued" in data["message"]
        assert response.headers["Retry-After"] == "42"
        mock_issue_code.assert_called_once_with(email)
        mock_cf_turnstile.assert_called_once()

    def test_cf_turnstile_enforced(
        self,
        settings: LazySettings,
        api_client: Client,
    ) -> None:
        response = api_client.post(self.path, data={"bad": "data"})
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert settings.CF_TURNSTILE_RESPONSE_HEADER_NAME in response.json()["message"]


class TestVerifyEmailVerification:
    path = reverse("api-1.0.0:verify-email-verification")

    @pytest.fixture
    def mock_verify_code(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.verikit.api.EmailVerificationService.verify_code")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        mock_verify_code: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        token = faker.pystr()
        mock_verify_code.return_value = token

        response = api_client.post(self.path, data={"email": email, "code": code})

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["email"] == email
        assert data["token"] == token
        mock_verify_code.assert_called_once_with(email, code)
        mock_cf_turnstile.assert_called_once()

    def test_invalid_or_expired_code(
        self,
        faker: Faker,
        api_client: Client,
        mock_verify_code: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        mock_verify_code.return_value = None

        response = api_client.post(self.path, data={"email": email, "code": code})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["message"] == "Invalid or expired verification code."
        mock_verify_code.assert_called_once_with(email, code)
        mock_cf_turnstile.assert_called_once()

    def test_cf_turnstile_enforced(
        self,
        settings: LazySettings,
        api_client: Client,
    ) -> None:
        response = api_client.post(self.path, data={"bad": "data"})
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert settings.CF_TURNSTILE_RESPONSE_HEADER_NAME in response.json()["message"]

    def test_payload_email_throttling_brute_force_protection(
        self,
        faker: Faker,
        api_client: Client,
        mock_verify_code: MagicMock,
        mock_cf_turnstile: MagicMock,
    ) -> None:
        # Prevent email conflicts with those used in other test cases.
        email = f"{faker.uuid4()}@example.com"
        wrong_code = "000000"
        mock_verify_code.return_value = None

        # First 20 attempts should work (return 422 for wrong code).
        for _ in range(20):
            response = api_client.post(
                self.path,
                data={"email": email, "code": wrong_code},
            )
            assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # 21st attempt should be throttled (429).
        response = api_client.post(self.path, data={"email": email, "code": wrong_code})
        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS

        # Different email should still work.
        different_email = faker.email()
        response = api_client.post(
            self.path,
            data={"email": different_email, "code": wrong_code},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        mock_cf_turnstile.assert_called()


@pytest.mark.django_db(transaction=True)
class TestEmailVerificationE2E:
    create_path = reverse("api-1.0.0:create-email-verification")
    verify_path = reverse("api-1.0.0:verify-email-verification")

    @pytest.fixture(autouse=True)
    def mock_code_interval(self, settings: LazySettings) -> None:
        settings.VERIKIT_EMAIL_CODE_INTERVAL = timedelta(seconds=60)

    @pytest.fixture(autouse=True)
    def mock_template(self, mocker: MockerFixture) -> None:
        mocker.patch.object(
            EmailVerificationService,
            "verification_email_template",
            EmailTemplate(
                format=EmailFormatName.TEXT,
                subject="Verification Code",
                body="Code: {{ code }}",
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
        email = faker.email()

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["email"] == email

        [sent_email] = mailoutbox
        assert sent_email.to == [email]

        email_body = sent_email.body
        code = email_body.removeprefix("Code: ").strip()

        response = api_client.post(
            self.verify_path,
            data={"email": email, "code": code},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["email"] == email
        token = data["token"]
        assert isinstance(token, str)

        verified_email = EmailVerificationService.verify_token(token)
        assert verified_email and verified_email.lower() == email.lower()

    def test_complete_flow_case_insensitive_email(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email().lower()
        email_upper = email.upper()

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        code = sent_email.body.removeprefix("Code: ").strip()

        response = api_client.post(
            self.verify_path,
            data={"email": email_upper, "code": code},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        token = data["token"]
        assert isinstance(token, str)

        verified_email = EmailVerificationService.verify_token(token)
        assert verified_email and verified_email.lower() == email.lower()

    def test_wrong_code_blocks_flow(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email()
        wrong_code = "000000"

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        correct_code = sent_email.body.removeprefix("Code: ").strip()
        assert wrong_code != correct_code

        response = api_client.post(
            self.verify_path,
            data={"email": email, "code": wrong_code},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["message"] == "Invalid or expired verification code."

    def test_expired_code_blocks_flow(
        self,
        faker: Faker,
        settings: LazySettings,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email()
        settings.VERIKIT_EMAIL_CODE_EXPIRY = timedelta(seconds=-1)

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        sent_email = mailoutbox[0]
        code = sent_email.body.removeprefix("Code: ").strip()

        response = api_client.post(
            self.verify_path,
            data={"email": email, "code": code},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["message"] == "Invalid or expired verification code."

    def test_rate_limiting_blocks_multiple_codes(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email()

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED
        assert len(mailoutbox) == 1

        # Verify rate limiting blocked the second email send.
        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        data = response.json()
        assert "verification code was recently issued" in data["message"]
        assert len(mailoutbox) == 1

    def test_used_code_cannot_be_reused(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
    ) -> None:
        email = faker.email()

        response = api_client.post(self.create_path, data={"email": email})
        assert response.status_code == HTTPStatus.CREATED

        code = mailoutbox[0].body.removeprefix("Code: ").strip()

        response = api_client.post(
            self.verify_path,
            data={"email": email, "code": code},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        token1 = data["token"]
        assert isinstance(token1, str)

        response = api_client.post(
            self.verify_path,
            data={"email": email, "code": code},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["message"] == "Invalid or expired verification code."

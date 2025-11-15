import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.verikit.models import EmailVerification
from app.verikit.services import EmailVerificationService
from tests.helpers import any_str


def create_email_verification(
    email: str,
    code: str | None = None,
    code_hash: str = "test_hash",
    create_time: datetime | None = None,
    expire_time: datetime | None = None,
    verify_time: datetime | None = None,
) -> EmailVerification:
    if code is not None:
        code_hash = EmailVerificationService.sign_code(email, code)
    if create_time is None:
        create_time = timezone.now()
    if expire_time is None:
        expire_time = timezone.now() + timedelta(minutes=30)
    return EmailVerification.objects.create(
        email=email,
        code_hash=code_hash,
        create_time=create_time,
        expire_time=expire_time,
        verify_time=verify_time,
    )


@pytest.mark.django_db(transaction=True)
class TestEmailVerificationServiceIssueCode:
    @pytest.fixture(autouse=True)
    def mock_code_interval(self, settings: LazySettings) -> None:
        settings.VERIKIT_EMAIL_CODE_INTERVAL = timedelta(seconds=60)

    @pytest.fixture
    def mock_send(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(
            EmailVerificationService,
            "send_verification_email",
        )

    def test_happy_path(
        self,
        faker: Faker,
        mocker: MockerFixture,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email()
        code = faker.pystr()
        mock_generate = mocker.patch.object(
            EmailVerificationService,
            "generate_code",
            return_value=code,
        )

        result = EmailVerificationService.issue_code(email)
        assert result is not None

        assert result.email == email
        assert result.code_hash == any_str
        assert result.expire_time > timezone.now()
        assert result.verify_time is None
        mock_generate.assert_called_once()
        mock_send.assert_called_once_with(email, code)

    def test_generates_unique_hashes(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email1 = faker.email()
        email2 = faker.email()

        result1 = EmailVerificationService.issue_code(email1)
        result2 = EmailVerificationService.issue_code(email2)
        assert result1 is not None
        assert result2 is not None

        assert result1.code_hash != result2.code_hash

    def test_returns_none_when_rate_limited(
        self,
        faker: Faker,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        create_email_verification(email, create_time=recent_time)

        result = EmailVerificationService.issue_code(email)
        assert result is None

        mock_send.assert_not_called()
        assert EmailVerification.objects.filter(email=email).count() == 1

    def test_allows_new_code_after_rate_limit_expires(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        old_time = timezone.now() - timedelta(seconds=120)
        create_email_verification(email, create_time=old_time)

        result = EmailVerificationService.issue_code(email)
        assert result is not None

        assert result.email == email

    def test_ignores_expired_verifications_for_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        create_email_verification(
            email,
            create_time=recent_time,
            expire_time=timezone.now() - timedelta(seconds=10),
        )

        result = EmailVerificationService.issue_code(email)
        assert result is not None

        assert result.email == email

    def test_ignores_verified_codes_for_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        create_email_verification(
            email,
            create_time=recent_time,
            verify_time=timezone.now(),
        )

        result = EmailVerificationService.issue_code(email)
        assert result is not None

        assert result.email == email

    def test_case_insensitive_email_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email().lower()
        email_upper = email.upper()
        recent_time = timezone.now() - timedelta(seconds=30)
        create_email_verification(email, create_time=recent_time)

        result = EmailVerificationService.issue_code(email_upper)
        assert result is None

        mock_send.assert_not_called()

    def test_uses_database_transaction(
        self,
        faker: Faker,
        mocker: MockerFixture,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email()
        mocker.patch.object(
            EmailVerification,
            "refresh_from_db",
            side_effect=Exception("Database error"),
        )

        with pytest.raises(Exception, match="Database error"):
            EmailVerificationService.issue_code(email)

        assert not EmailVerification.objects.filter(email=email).exists()
        mock_send.assert_not_called()

    async def test_concurrent_requests_for_same_email(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()

        async def issue_code_task() -> EmailVerification | None:
            return await sync_to_async(EmailVerificationService.issue_code)(email)

        results = await asyncio.gather(
            issue_code_task(),
            issue_code_task(),
            return_exceptions=True,
        )

        successful_results = [
            r for r in results if r is not None and not isinstance(r, BaseException)
        ]
        none_results = [r for r in results if r is None]

        assert len(successful_results) == 1
        assert len(none_results) == 1
        assert successful_results[0].email == email


@pytest.mark.django_db(transaction=True)
class TestEmailVerificationServiceVerifyCode:
    @pytest.fixture
    def mock_issue_token(self, mocker: MockerFixture, faker: Faker) -> MagicMock:
        return mocker.patch.object(
            EmailVerificationService,
            "issue_token",
            return_value=faker.pystr(),
        )

    def test_happy_path(self, faker: Faker, mock_issue_token: MagicMock) -> None:
        email = faker.email()
        code = "123456"
        verification = create_email_verification(email=email, code=code)

        result = EmailVerificationService.verify_code(email, code)
        assert result == mock_issue_token.return_value

        mock_issue_token.assert_called_once_with(email)

        verification.refresh_from_db()
        assert verification.verify_time is not None

    def test_returns_none_for_invalid_code(self, faker: Faker) -> None:
        email = faker.email()
        correct_code = "123456"
        wrong_code = "654321"
        verification = create_email_verification(email=email, code=correct_code)

        result = EmailVerificationService.verify_code(email, wrong_code)
        assert result is None

        verification.refresh_from_db()
        assert verification.verify_time is None

    def test_returns_none_for_nonexistent_email(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"

        result = EmailVerificationService.verify_code(email, code)
        assert result is None

    def test_returns_none_for_expired_verification(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"
        create_email_verification(
            email=email,
            code=code,
            expire_time=timezone.now() - timedelta(minutes=1),
        )

        result = EmailVerificationService.verify_code(email, code)
        assert result is None

    def test_returns_none_for_already_verified_code(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"
        create_email_verification(
            email=email,
            code=code,
            verify_time=timezone.now() - timedelta(minutes=1),
        )

        result = EmailVerificationService.verify_code(email, code)
        assert result is None

    def test_invalidates_all_active_verifications_on_success(
        self,
        faker: Faker,
        mock_issue_token: MagicMock,
    ) -> None:
        email = faker.email()
        code1 = "123456"
        code2 = "654321"
        verification1 = create_email_verification(email=email, code=code1)
        verification2 = create_email_verification(email=email, code=code2)

        result = EmailVerificationService.verify_code(email, code1)
        assert result == mock_issue_token.return_value

        verification1.refresh_from_db()
        assert verification1.verify_time is not None
        verification2.refresh_from_db()
        assert verification2.verify_time is not None

    def test_case_insensitive_email_matching(
        self,
        faker: Faker,
        mock_issue_token: MagicMock,
    ) -> None:
        email = faker.email().lower()
        email_upper = email.upper()
        code = "123456"
        create_email_verification(email=email, code=code)

        result = EmailVerificationService.verify_code(email_upper, code)
        assert result == mock_issue_token.return_value

        mock_issue_token.assert_called_once_with(email_upper)

    def test_verifies_with_any_matching_active_code(
        self,
        faker: Faker,
        mock_issue_token: MagicMock,
    ) -> None:
        email = faker.email()
        code1 = "123456"
        code2 = "654321"
        create_email_verification(email=email, code=code1)
        create_email_verification(email=email, code=code2)

        result = EmailVerificationService.verify_code(email, code2)
        assert result == mock_issue_token.return_value

    def test_uses_database_transaction(
        self,
        faker: Faker,
        mock_issue_token: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        verification = create_email_verification(email=email, code=code)
        mock_issue_token.side_effect = Exception("Token signing failed")

        with pytest.raises(Exception, match="Token signing failed"):
            EmailVerificationService.verify_code(email, code)

        verification.refresh_from_db()
        assert verification.verify_time is None

    async def test_concurrent_verification_attempts(
        self,
        faker: Faker,
        mock_issue_token: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        await sync_to_async(create_email_verification)(email=email, code=code)

        async def verify_task() -> str | None:
            return await sync_to_async(EmailVerificationService.verify_code)(
                email,
                code,
            )

        results = await asyncio.gather(
            verify_task(),
            verify_task(),
            return_exceptions=True,
        )

        successful_results = [
            r
            for r in results
            if r == mock_issue_token.return_value and not isinstance(r, BaseException)
        ]
        none_results = [r for r in results if r is None]

        assert len(successful_results) == 1
        assert len(none_results) == 1


class TestEmailVerificationServiceVerifyToken:
    def test_happy_path(self, faker: Faker) -> None:
        email = faker.email()
        token = EmailVerificationService.issue_token(email)

        verified_email = EmailVerificationService.verify_token(token)

        assert verified_email is not None
        assert verified_email.casefold() == email.casefold()

    def test_returns_false_for_expired_token(
        self,
        faker: Faker,
        settings: LazySettings,
    ) -> None:
        email = faker.email()
        settings.VERIKIT_EMAIL_TOKEN_EXPIRY = timedelta()
        token = EmailVerificationService.issue_token(email)

        verified_email = EmailVerificationService.verify_token(token)

        assert verified_email is None

    @pytest.mark.parametrize(
        "invalid_token",
        [
            "",
            "just.a.string",
            "not-a-sig",
            "header.payload",
            "header.payload.signature.extra",
        ],
    )
    def test_returns_false_for_malformed_tokens(
        self,
        invalid_token: str,
    ) -> None:
        verified_email = EmailVerificationService.verify_token(invalid_token)

        assert verified_email is None

    def test_returns_false_for_tampered_token(self, faker: Faker) -> None:
        token = EmailVerificationService.issue_token(faker.email())
        tampered_token = f"{token}tampered"

        verified_email = EmailVerificationService.verify_token(tampered_token)

        assert verified_email is None

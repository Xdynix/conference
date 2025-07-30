import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.verikit.models import EmailVerification
from app.verikit.services import EmailVerificationService
from tests.helpers import any_bytes


async def create_email_verification(
    email: str,
    code: str | None = None,
    code_salt: bytes = b"test_salt",
    code_hash: bytes = b"test_hash",
    create_time: datetime | None = None,
    expire_time: datetime | None = None,
    verify_time: datetime | None = None,
) -> EmailVerification:
    if code is not None:
        code_salt, code_hash = EmailVerificationService.hash_code(code)
    if create_time is None:
        create_time = timezone.now()
    if expire_time is None:
        expire_time = timezone.now() + timedelta(minutes=30)
    return await EmailVerification.objects.acreate(
        email=email,
        code_salt=code_salt,
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

    async def test_happy_path(
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

        result = await EmailVerificationService.issue_code(email)

        assert result is not None
        assert result.email == email
        assert result.code_salt == any_bytes
        assert result.code_hash == any_bytes
        assert result.expire_time > timezone.now()
        assert result.verify_time is None
        mock_generate.assert_called_once()
        mock_send.assert_called_once_with(email, code)

    async def test_generates_unique_salt_and_hash(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email1 = faker.email()
        email2 = faker.email()
        result1 = await EmailVerificationService.issue_code(email1)
        result2 = await EmailVerificationService.issue_code(email2)

        assert result1 is not None
        assert result2 is not None
        assert result1.code_salt != result2.code_salt
        assert result1.code_hash != result2.code_hash

    async def test_returns_none_when_rate_limited(
        self,
        faker: Faker,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        await create_email_verification(email, create_time=recent_time)

        result = await EmailVerificationService.issue_code(email)

        assert result is None
        mock_send.assert_not_called()
        assert await EmailVerification.objects.filter(email=email).acount() == 1

    async def test_allows_new_code_after_rate_limit_expires(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        old_time = timezone.now() - timedelta(seconds=120)
        await create_email_verification(email, create_time=old_time)

        result = await EmailVerificationService.issue_code(email)

        assert result is not None
        assert result.email == email

    async def test_ignores_expired_verifications_for_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        await create_email_verification(
            email,
            create_time=recent_time,
            expire_time=timezone.now() - timedelta(seconds=10),
        )

        result = await EmailVerificationService.issue_code(email)

        assert result is not None
        assert result.email == email

    async def test_ignores_verified_codes_for_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()
        recent_time = timezone.now() - timedelta(seconds=30)
        await create_email_verification(
            email,
            create_time=recent_time,
            verify_time=timezone.now(),
        )

        result = await EmailVerificationService.issue_code(email)

        assert result is not None
        assert result.email == email

    async def test_case_insensitive_email_rate_limiting(
        self,
        faker: Faker,
        mock_send: MagicMock,
    ) -> None:
        email = faker.email().lower()
        email_upper = email.upper()
        recent_time = timezone.now() - timedelta(seconds=30)
        await create_email_verification(email, create_time=recent_time)

        result = await EmailVerificationService.issue_code(email_upper)

        assert result is None
        mock_send.assert_not_called()

    async def test_uses_database_transaction(
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
            await EmailVerificationService.issue_code(email)

        assert not await EmailVerification.objects.filter(email=email).aexists()
        mock_send.assert_not_called()

    async def test_concurrent_requests_for_same_email(
        self,
        faker: Faker,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        email = faker.email()

        async def issue_code_task() -> EmailVerification | None:
            return await EmailVerificationService.issue_code(email)

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
    def mock_sign_jwt(self, mocker: MockerFixture, faker: Faker) -> MagicMock:
        return mocker.patch.object(
            EmailVerificationService,
            "sign_jwt",
            return_value=faker.pystr(),
        )

    async def test_happy_path(self, faker: Faker, mock_sign_jwt: MagicMock) -> None:
        email = faker.email()
        code = "123456"
        verification = await create_email_verification(email=email, code=code)

        result = await EmailVerificationService.verify_code(email, code)

        assert result == mock_sign_jwt.return_value
        mock_sign_jwt.assert_called_once_with(email)

        await verification.arefresh_from_db()
        assert verification.verify_time is not None

    async def test_returns_none_for_invalid_code(self, faker: Faker) -> None:
        email = faker.email()
        correct_code = "123456"
        wrong_code = "654321"
        verification = await create_email_verification(email=email, code=correct_code)

        result = await EmailVerificationService.verify_code(email, wrong_code)

        assert result is None
        await verification.arefresh_from_db()
        assert verification.verify_time is None

    async def test_returns_none_for_nonexistent_email(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"

        result = await EmailVerificationService.verify_code(email, code)

        assert result is None

    async def test_returns_none_for_expired_verification(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"
        await create_email_verification(
            email=email,
            code=code,
            expire_time=timezone.now() - timedelta(minutes=1),
        )

        result = await EmailVerificationService.verify_code(email, code)

        assert result is None

    async def test_returns_none_for_already_verified_code(self, faker: Faker) -> None:
        email = faker.email()
        code = "123456"
        await create_email_verification(
            email=email,
            code=code,
            verify_time=timezone.now() - timedelta(minutes=1),
        )

        result = await EmailVerificationService.verify_code(email, code)

        assert result is None

    async def test_invalidates_all_active_verifications_on_success(
        self,
        faker: Faker,
        mock_sign_jwt: MagicMock,
    ) -> None:
        email = faker.email()
        code1 = "123456"
        code2 = "654321"
        verification1 = await create_email_verification(email=email, code=code1)
        verification2 = await create_email_verification(email=email, code=code2)

        result = await EmailVerificationService.verify_code(email, code1)

        assert result == mock_sign_jwt.return_value

        await verification1.arefresh_from_db()
        await verification2.arefresh_from_db()
        assert verification1.verify_time is not None
        assert verification2.verify_time is not None

    async def test_case_insensitive_email_matching(
        self,
        faker: Faker,
        mock_sign_jwt: MagicMock,
    ) -> None:
        email = faker.email().lower()
        email_upper = email.upper()
        code = "123456"
        await create_email_verification(email=email, code=code)

        result = await EmailVerificationService.verify_code(email_upper, code)

        assert result == mock_sign_jwt.return_value
        mock_sign_jwt.assert_called_once_with(email_upper)

    async def test_verifies_with_any_matching_active_code(
        self,
        faker: Faker,
        mock_sign_jwt: MagicMock,
    ) -> None:
        email = faker.email()
        code1 = "123456"
        code2 = "654321"
        await create_email_verification(email=email, code=code1)
        await create_email_verification(email=email, code=code2)

        result = await EmailVerificationService.verify_code(email, code2)

        assert result == mock_sign_jwt.return_value

    async def test_uses_database_transaction(
        self,
        faker: Faker,
        mock_sign_jwt: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        verification = await create_email_verification(email=email, code=code)
        mock_sign_jwt.side_effect = Exception("JWT signing failed")

        with pytest.raises(Exception, match="JWT signing failed"):
            await EmailVerificationService.verify_code(email, code)

        await verification.arefresh_from_db()
        assert verification.verify_time is None

    async def test_concurrent_verification_attempts(
        self,
        faker: Faker,
        mock_sign_jwt: MagicMock,
    ) -> None:
        email = faker.email()
        code = "123456"
        await create_email_verification(email=email, code=code)

        async def verify_task() -> str | None:
            return await EmailVerificationService.verify_code(email, code)

        results = await asyncio.gather(
            verify_task(),
            verify_task(),
            return_exceptions=True,
        )

        successful_results = [
            r
            for r in results
            if r == mock_sign_jwt.return_value and not isinstance(r, BaseException)
        ]
        none_results = [r for r in results if r is None]

        assert len(successful_results) == 1
        assert len(none_results) == 1


class TestEmailVerificationServiceVerifyToken:
    def test_happy_path(self, faker: Faker) -> None:
        email = faker.email()
        token = EmailVerificationService.sign_jwt(email)

        result = EmailVerificationService.verify_token(email, token)

        assert result is True

    def test_returns_false_for_mismatched_email(self, faker: Faker) -> None:
        email1 = faker.email()
        email2 = faker.email()
        token = EmailVerificationService.sign_jwt(email1)

        result = EmailVerificationService.verify_token(email2, token)

        assert result is False

    def test_returns_false_for_expired_token(
        self,
        faker: Faker,
        settings: LazySettings,
    ) -> None:
        email = faker.email()
        settings.VERIKIT_EMAIL_TOKEN_EXPIRY = timedelta(microseconds=1)
        token = EmailVerificationService.sign_jwt(email)

        result = EmailVerificationService.verify_token(email, token)

        assert result is False

    @pytest.mark.parametrize(
        "invalid_token",
        [
            "",
            "just.a.string",
            "not-a-jwt",
            "header.payload",
            "header.payload.signature.extra",
            "invalid.jwt.token",
        ],
    )
    def test_returns_false_for_malformed_tokens(
        self,
        faker: Faker,
        invalid_token: str,
    ) -> None:
        email = faker.email()

        result = EmailVerificationService.verify_token(email, invalid_token)

        assert result is False

    def test_returns_false_for_token_with_wrong_secret(self, faker: Faker) -> None:
        email = faker.email()
        token_with_wrong_secret = jwt.encode(
            {"sub": email},
            "wrong-secret-key",
            algorithm="HS256",
        )

        result = EmailVerificationService.verify_token(email, token_with_wrong_secret)

        assert result is False

    def test_case_insensitive_email_comparison(self, faker: Faker) -> None:
        email = faker.email().lower()
        email_upper = email.upper()
        token = EmailVerificationService.sign_jwt(email)

        result = EmailVerificationService.verify_token(email_upper, token)

        assert result is True

    def test_returns_false_for_token_with_missing_subject(
        self,
        faker: Faker,
        settings: LazySettings,
    ) -> None:
        email = faker.email()
        token_without_subject = jwt.encode(
            {"iat": timezone.now().timestamp()},
            settings.VERIKIT_EMAIL_TOKEN_SECRET,
            algorithm="HS256",
        )

        result = EmailVerificationService.verify_token(email, token_without_subject)

        assert result is False

    def test_returns_false_for_token_with_null_subject(
        self,
        faker: Faker,
        settings: LazySettings,
    ) -> None:
        email = faker.email()
        token_with_null_subject = jwt.encode(
            {"sub": None},
            settings.VERIKIT_EMAIL_TOKEN_SECRET,
            algorithm="HS256",
        )

        result = EmailVerificationService.verify_token(email, token_with_null_subject)

        assert result is False

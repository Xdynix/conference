import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker
from pydantic import HttpUrl
from pytest_mock import MockerFixture

from app.core.models import PasswordResetToken, User
from app.core.services import PasswordResetService
from app.core.services.password_reset import PasswordResetEmailContext
from app.core.types import Password
from app.utils.email import EmailFormatName, EmailTemplate


def create_password_reset_token(
    user: User,
    token: str | None = None,
    token_hash: str | None = None,
    create_time: datetime | None = None,
    expire_time: datetime | None = None,
    consume_time: datetime | None = None,
) -> PasswordResetToken:
    if token is not None:
        token_hash = PasswordResetService.hash_token(token)
    if token_hash is None:
        token_hash = "test_token_hash"
    if create_time is None:
        create_time = timezone.now()
    if expire_time is None:
        expire_time = timezone.now() + timedelta(hours=1)

    return PasswordResetToken.objects.create(
        user=user,
        token_hash=token_hash,
        create_time=create_time,
        expire_time=expire_time,
        consume_time=consume_time,
    )


@pytest.mark.django_db(transaction=True)
class TestPasswordResetServiceCreateToken:
    @pytest.fixture(autouse=True)
    def mock_token_interval(self, settings: LazySettings) -> None:
        settings.PASSWORD_RESET_TOKEN_INTERVAL = timedelta(seconds=60)

    @pytest.fixture(autouse=True)
    def mock_token_expiry(self, settings: LazySettings) -> None:
        settings.PASSWORD_RESET_TOKEN_EXPIRY = timedelta(hours=1)

    @pytest.fixture
    def mock_send_email(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(
            PasswordResetService,
            "send_password_reset_email",
        )

    def test_happy_path(
        self,
        faker: Faker,
        mocker: MockerFixture,
        mock_send_email: MagicMock,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        token = "test_token_123"
        mock_generate = mocker.patch.object(
            PasswordResetService,
            "generate_token",
            return_value=token,
        )

        result = PasswordResetService.create_token(
            user,
            password_reset_page_uri=faker.uri_page(),
        )
        assert result is not None

        assert result.user_id == user.id
        assert result.token_hash == PasswordResetService.hash_token(token)
        assert result.expire_time > timezone.now()
        assert result.consume_time is None
        mock_generate.assert_called_once()
        mock_send_email.assert_called_once_with(
            user,
            token,
            password_reset_page_uri=mocker.ANY,
        )

    def test_returns_none_when_rate_limited(
        self,
        faker: Faker,
        mock_send_email: MagicMock,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        recent_time = timezone.now() - timedelta(seconds=30)
        create_password_reset_token(user, create_time=recent_time)

        result = PasswordResetService.create_token(
            user,
            password_reset_page_uri=faker.uri_page(),
        )
        assert result is None

        mock_send_email.assert_not_called()
        assert PasswordResetToken.objects.filter(user=user).count() == 1

    def test_allows_new_token_after_rate_limit_expires(
        self,
        faker: Faker,
        mock_send_email: MagicMock,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        old_time = timezone.now() - timedelta(seconds=120)
        create_password_reset_token(user, create_time=old_time)

        result = PasswordResetService.create_token(
            user,
            password_reset_page_uri=faker.uri_page(),
        )
        assert result is not None

        assert result.user_id == user.id
        mock_send_email.assert_called_once()

    def test_uses_database_transaction(
        self,
        faker: Faker,
        mocker: MockerFixture,
        mock_send_email: MagicMock,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        mocker.patch.object(
            PasswordResetToken,
            "refresh_from_db",
            side_effect=Exception("Database error"),
        )

        with pytest.raises(Exception, match="Database error"):
            PasswordResetService.create_token(
                user,
                password_reset_page_uri=faker.uri_page(),
            )

        assert not PasswordResetToken.objects.filter(user=user).exists()
        mock_send_email.assert_not_called()

    async def test_concurrent_requests_for_same_user(
        self,
        faker: Faker,
        mock_send_email: MagicMock,
    ) -> None:
        user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        async def create_token_task() -> PasswordResetToken | None:
            return await sync_to_async(PasswordResetService.create_token)(
                user,
                password_reset_page_uri=faker.uri_page(),
            )

        results = await asyncio.gather(
            create_token_task(),
            create_token_task(),
            return_exceptions=True,
        )

        successful_results = [
            r for r in results if r is not None and not isinstance(r, BaseException)
        ]
        none_results = [r for r in results if r is None]

        assert len(successful_results) == 1
        assert len(none_results) == 1
        assert successful_results[0].user_id == user.id
        mock_send_email.assert_called_once()


@pytest.mark.django_db(transaction=True)
class TestPasswordResetServiceConsumeToken:
    def test_happy_path(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token = "test_token_123"
        token_obj = create_password_reset_token(user, token=token)

        result = PasswordResetService.consume_token(
            user,
            token,
            Password(new_password),
        )
        assert result is True

        user.refresh_from_db()
        assert not user.check_password(old_password)
        assert user.check_password(new_password)

        token_obj.refresh_from_db()
        assert token_obj.consume_time is not None

    def test_returns_false_for_invalid_token(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        correct_token = "test_token_123"
        wrong_token = "wrong_token_456"
        token_obj = create_password_reset_token(user, token=correct_token)

        result = PasswordResetService.consume_token(
            user,
            wrong_token,
            Password(new_password),
        )
        assert result is False

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

        token_obj.refresh_from_db()
        assert token_obj.consume_time is None

    def test_returns_false_for_expired_token(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token = "test_token_123"
        token_obj = create_password_reset_token(
            user,
            token=token,
            expire_time=timezone.now() - timedelta(minutes=1),
        )

        result = PasswordResetService.consume_token(
            user,
            token,
            Password(new_password),
        )
        assert result is False

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

        token_obj.refresh_from_db()
        assert token_obj.consume_time is None

    def test_returns_false_for_already_consumed_token(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token = "test_token_123"
        create_password_reset_token(
            user,
            token=token,
            consume_time=timezone.now() - timedelta(minutes=1),
        )

        result = PasswordResetService.consume_token(
            user,
            token,
            Password(new_password),
        )
        assert result is False

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

    def test_invalidates_all_active_tokens_on_success(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token1 = "test_token_123"
        token2 = "test_token_456"
        token_obj1 = create_password_reset_token(user, token=token1)
        token_obj2 = create_password_reset_token(user, token=token2)

        result = PasswordResetService.consume_token(
            user,
            token1,
            Password(new_password),
        )
        assert result is True

        user.refresh_from_db()
        assert not user.check_password(old_password)
        assert user.check_password(new_password)

        token_obj1.refresh_from_db()
        assert token_obj1.consume_time is not None
        assert token_obj1.expire_time > timezone.now()
        token_obj2.refresh_from_db()
        assert token_obj2.consume_time is None
        assert token_obj2.expire_time <= timezone.now()

    def test_uses_database_transaction(
        self,
        faker: Faker,
        mocker: MockerFixture,
    ) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token = "test_token_123"
        token_obj = create_password_reset_token(user, token=token)

        mocker.patch.object(
            user,
            "save",
            side_effect=Exception("Password update failed"),
        )

        with pytest.raises(Exception, match="Password update failed"):
            PasswordResetService.consume_token(
                user,
                token,
                Password(new_password),
            )

        user.refresh_from_db()
        assert user.check_password(old_password)
        assert not user.check_password(new_password)

        token_obj.refresh_from_db()
        assert token_obj.consume_time is None

    async def test_concurrent_consumption_attempts(self, faker: Faker) -> None:
        old_password = faker.password()
        new_password = faker.password()
        user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
            password=old_password,
        )
        token = "test_token_123"
        await sync_to_async(create_password_reset_token)(user, token=token)

        async def consume_task() -> bool:
            return await sync_to_async(PasswordResetService.consume_token)(
                user,
                token,
                Password(new_password),
            )

        results = await asyncio.gather(
            consume_task(),
            consume_task(),
            return_exceptions=True,
        )

        successful_results = [r for r in results if r is True]
        false_results = [r for r in results if r is False]

        assert len(successful_results) == 1
        assert len(false_results) == 1


class TestPasswordResetServiceTemplate:
    def test_default_template_configuration(self, faker: Faker) -> None:
        template = PasswordResetService.password_reset_email_template

        assert isinstance(template, EmailTemplate)
        assert template.format == EmailFormatName.TEXT

        context = PasswordResetEmailContext(
            site_name=faker.company(),
            reset_link=HttpUrl(faker.url()),
            reset_link_expiry_minutes=60,
            username=faker.user_name(),
        )
        rendered = template.render(context)

        assert rendered.format == EmailFormatName.TEXT
        assert str(context.reset_link) in rendered.body
        assert len(rendered.subject) > 0

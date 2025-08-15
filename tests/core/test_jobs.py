from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker

from app.core.jobs import cleanup_expired_password_reset_tokens
from app.core.models import PasswordResetToken, User
from app.infra.services import scheduler


@pytest.mark.django_db
def test_cleanup_expired_password_reset_tokens(
    faker: Faker,
    settings: LazySettings,
) -> None:
    user = User.objects.create_user(username=faker.user_name())

    now = timezone.now()
    expired_time = now - timedelta(days=1) - settings.PASSWORD_RESET_TOKEN_RETENTION
    not_expired_time = now + timedelta(days=1)

    expired = PasswordResetToken.objects.create(
        user=user,
        token_hash=faker.pystr(),
        create_time=expired_time,
        expire_time=now,
    )
    not_expired = PasswordResetToken.objects.create(
        user=user,
        token_hash=faker.pystr(),
        create_time=not_expired_time,
        expire_time=now,
    )
    assert PasswordResetToken.objects.count() == 2

    cleanup_expired_password_reset_tokens()

    assert not PasswordResetToken.objects.filter(id=expired.id).exists()
    assert PasswordResetToken.objects.filter(id=not_expired.id).exists()


def test_job_scheduled() -> None:
    assert (
        sum(
            job.func is cleanup_expired_password_reset_tokens
            for job in scheduler.get_jobs()
        )
        == 1
    )

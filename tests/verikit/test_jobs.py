from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker

from app.infra.services import scheduler
from app.verikit.jobs import cleanup_expired_verifications
from app.verikit.models import EmailVerification


@pytest.mark.django_db
def test_cleanup_expired_verifications(faker: Faker, settings: LazySettings) -> None:
    now = timezone.now()
    expired_time = now - timedelta(days=1) - settings.VERIKIT_VERIFICATION_RETENTION
    not_expired_time = now + timedelta(days=1)

    expired = EmailVerification.objects.create(
        email=faker.email(),
        code_hash="hash",
        create_time=expired_time,
        expire_time=now,
    )
    not_expired = EmailVerification.objects.create(
        email=faker.email(),
        code_hash="hash",
        create_time=not_expired_time,
        expire_time=now,
    )
    assert EmailVerification.objects.count() == 2

    cleanup_expired_verifications()

    assert not EmailVerification.objects.filter(id=expired.id).exists()
    assert EmailVerification.objects.filter(id=not_expired.id).exists()


def test_job_scheduled() -> None:
    assert (
        sum(job.func is cleanup_expired_verifications for job in scheduler.get_jobs())
        == 1
    )

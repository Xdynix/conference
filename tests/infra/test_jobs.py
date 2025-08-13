from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker

from app.infra.jobs import cleanup_expired_mutexes
from app.infra.models import Mutex
from app.infra.services import scheduler


@pytest.mark.django_db
def test_cleanup_expired_mutexes(faker: Faker, settings: LazySettings) -> None:
    now = timezone.now()
    expired_time = now - timedelta(days=1) - settings.MUTEX_RETENTION
    not_expired_time = now + timedelta(days=1)

    expired = Mutex.objects.create(
        key_hash=faker.sha256(),
        touch_time=expired_time,
    )
    not_expired = Mutex.objects.create(
        key_hash=faker.sha256(),
        touch_time=not_expired_time,
    )
    assert Mutex.objects.count() == 2

    cleanup_expired_mutexes()

    assert not Mutex.objects.filter(pk=expired.pk).exists()
    assert Mutex.objects.filter(pk=not_expired.pk).exists()


def test_job_scheduled() -> None:
    assert sum(job.func is cleanup_expired_mutexes for job in scheduler.get_jobs()) == 1

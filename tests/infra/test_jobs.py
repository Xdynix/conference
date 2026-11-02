from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.utils import timezone
from faker import Faker
from post_office.management.commands.cleanup_mail import Command as CleanupMailCommand
from post_office.models import STATUS, Email
from pytest_mock import MockerFixture

from app.infra import jobs
from app.infra.models import Mutex
from app.infra.services import scheduler


@pytest.mark.parametrize(
    "job_func",
    [
        jobs.cleanup_expired_mutexes,
        jobs.deliver_queued_mail,
        jobs.cleanup_mail,
        jobs.report_mail_failures,
    ],
)
def test_job_scheduled(job_func: Callable[..., Any]) -> None:
    assert sum(job.func is job_func for job in scheduler.get_jobs()) == 1


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

    jobs.cleanup_expired_mutexes()

    assert not Mutex.objects.filter(pk=expired.pk).exists()
    assert Mutex.objects.filter(pk=not_expired.pk).exists()


def make_email(status: int, **fields: Any) -> Email:
    email = Email.objects.create(
        from_email="sender@example.com",
        to=["recipient@example.com"],
        status=status,
        scheduled_time=fields.pop("scheduled_time", None),
    )
    if fields:
        Email.objects.filter(pk=email.pk).update(**fields)
    return email


def send_one_queued_email() -> None:
    first = Email.objects.filter(status=STATUS.queued).order_by("id").first()
    Email.objects.filter(pk=first.pk).update(status=STATUS.sent)


@pytest.fixture
def send(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("app.infra.jobs.send_queued", side_effect=send_one_queued_email)


@pytest.mark.django_db
def test_deliver_queued_mail_skips_empty_queue(send: MagicMock) -> None:
    jobs.deliver_queued_mail()

    send.assert_not_called()


@pytest.mark.django_db
def test_deliver_queued_mail_sends_until_empty(send: MagicMock) -> None:
    make_email(STATUS.queued)
    make_email(STATUS.queued)

    jobs.deliver_queued_mail()

    assert send.call_count == 2


@pytest.mark.django_db
def test_deliver_queued_mail_stops_at_budget(
    send: MagicMock,
    mocker: MockerFixture,
) -> None:
    clock = mocker.patch("app.infra.jobs.time")
    # Deadline, loop check, batch start, batch end (3 s), loop check: 3 s left, so a
    # second 3 s batch would overrun.
    clock.monotonic.side_effect = [0.0, 0.0, 0.0, 3.0, 3.0]
    make_email(STATUS.queued)
    make_email(STATUS.queued)

    jobs.deliver_queued_mail()

    send.assert_called_once_with()


def test_cleanup_mail(mocker: MockerFixture) -> None:
    execute = mocker.patch.object(CleanupMailCommand, "execute")

    jobs.cleanup_mail()

    execute.assert_called_once()
    assert execute.call_args.kwargs["days"] == 30
    assert execute.call_args.kwargs["delete_attachments"] is True


@pytest.fixture
def mail_logs(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    return (
        mocker.patch("app.infra.jobs.logger.error"),
        mocker.patch("app.infra.jobs.logger.warning"),
    )


@pytest.mark.django_db
def test_report_mail_failures_counts_failed_rows(
    mail_logs: tuple[MagicMock, MagicMock],
) -> None:
    error, warning = mail_logs
    make_email(STATUS.failed)
    make_email(STATUS.failed, last_updated=timezone.now() - timedelta(days=2))
    make_email(STATUS.sent)

    jobs.report_mail_failures()

    error.assert_called_once_with(
        "Mail delivery failed permanently; requeue from the admin.", count=2
    )
    warning.assert_not_called()


@pytest.mark.django_db
def test_report_mail_failures_warns_about_retrying_rows(
    mail_logs: tuple[MagicMock, MagicMock],
) -> None:
    error, warning = mail_logs
    now = timezone.now()
    make_email(
        STATUS.requeued,
        created=now - timedelta(hours=3),
        scheduled_time=now + timedelta(minutes=10),
    )
    make_email(STATUS.requeued, created=now - timedelta(minutes=40))
    make_email(STATUS.queued, created=now - timedelta(hours=5))
    make_email(STATUS.sent, created=now - timedelta(hours=5))

    jobs.report_mail_failures()

    warning.assert_called_once_with(
        "Mail delivery is failing and retries are pending.",
        count=2,
        waiting_minutes=180,
    )
    error.assert_not_called()


@pytest.mark.django_db
def test_report_mail_failures_reports_both_states(
    mail_logs: tuple[MagicMock, MagicMock],
) -> None:
    error, warning = mail_logs
    make_email(STATUS.failed)
    make_email(STATUS.requeued)

    jobs.report_mail_failures()

    error.assert_called_once()
    warning.assert_called_once()


@pytest.mark.django_db
def test_report_mail_failures_silent_when_nothing_fails(
    mail_logs: tuple[MagicMock, MagicMock],
) -> None:
    error, warning = mail_logs
    make_email(STATUS.queued)
    make_email(STATUS.sent)

    jobs.report_mail_failures()

    error.assert_not_called()
    warning.assert_not_called()

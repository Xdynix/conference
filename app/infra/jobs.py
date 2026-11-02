import time
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.db.models import Count, Min, Q
from django.db.models.functions import Now
from django.utils import timezone
from loguru import logger
from post_office.mail import get_queued, send_queued
from post_office.models import STATUS, Email

from app.infra.models import Mutex
from app.infra.services import scheduler

# Shorter than the interval of deliver_queued_mail. The loop stops starting batches
# once the last one's duration would not fit, so a run normally ends before the next
# is due.
DELIVERY_BUDGET = timedelta(seconds=4)


@scheduler.scheduled_job("cron", hour="*/6", jitter=120)
def cleanup_expired_mutexes() -> None:
    deleted_count, _ = Mutex.objects.filter(
        touch_time__lt=Now() - settings.MUTEX_RETENTION
    ).delete()
    if deleted_count:  # pragma: no branch
        logger.info(
            "Cleaned up expired mutexes.",
            deleted_count=deleted_count,
        )


@scheduler.scheduled_job("interval", seconds=5)
def deliver_queued_mail() -> None:
    # A short tick bounds the delay for time-sensitive mail such as verification codes.
    deadline = time.monotonic() + DELIVERY_BUDGET.total_seconds()
    batch_seconds = 0.0
    while get_queued().exists() and time.monotonic() + batch_seconds < deadline:
        started = time.monotonic()
        send_queued()
        batch_seconds = time.monotonic() - started


@scheduler.scheduled_job("cron", hour="*/12", jitter=120)
def cleanup_mail() -> None:
    # A month keeps delivered and failed mail inspectable in the admin.
    call_command("cleanup_mail", days=30, delete_attachments=True)


@scheduler.scheduled_job("interval", minutes=10, jitter=60)
def report_mail_failures() -> None:
    """Log while any mail is failing to deliver.

    Permanently failed messages log an error and messages awaiting an automatic retry
    log a warning. Both repeat until the messages are delivered, requeued from the
    admin or cleaned up, so nothing is missed across a scheduler restart.
    """
    retrying = Q(status=STATUS.requeued)
    counts = Email.objects.aggregate(
        failed=Count("id", filter=Q(status=STATUS.failed)),
        retrying=Count("id", filter=retrying),
        oldest_retrying=Min("created", filter=retrying),
    )
    if counts["failed"]:
        logger.error(
            "Mail delivery failed permanently; requeue from the admin.",
            count=counts["failed"],
        )
    if counts["retrying"]:
        waiting = timezone.now() - counts["oldest_retrying"]
        logger.warning(
            "Mail delivery is failing and retries are pending.",
            count=counts["retrying"],
            waiting_minutes=int(waiting.total_seconds() // 60),
        )

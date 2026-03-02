import shutil

from django.conf import settings
from django.core.management import call_command
from loguru import logger

from app.infra.services import scheduler


@scheduler.scheduled_job("cron", hour="*/6", jitter=120)
def clear_sessions() -> None:
    call_command("clearsessions")


@scheduler.scheduled_job("cron", minute="*/20", jitter=120)
def retry_deferred() -> None:
    call_command("retry_deferred")


@scheduler.scheduled_job("cron", hour="*/12", jitter=120)
def purge_mail_log() -> None:
    call_command("purge_mail_log", 30)


@scheduler.scheduled_job("interval", minutes=10, jitter=60)
def check_disk_usage() -> None:
    """Log an error when free disk space drops below the configured threshold."""
    usage = shutil.disk_usage("/")
    free_gb = usage.free / (1024**3)
    if free_gb >= settings.DISK_FREE_THRESHOLD:
        return

    logger.error(
        "Free disk space below threshold.",
        free_gb=round(free_gb, 2),
        total_gb=round(usage.total / (1024**3), 2),
        threshold_gb=settings.DISK_FREE_THRESHOLD,
    )

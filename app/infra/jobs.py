from django.conf import settings
from django.db.models.functions import Now
from loguru import logger

from app.infra.models import Mutex
from app.infra.services import scheduler


@scheduler.scheduled_job("cron", hour="*/6", jitter=120)
def cleanup_expired_mutexes() -> None:
    deleted_count, _ = Mutex.objects.filter(
        touch_time__lt=Now() - settings.MUTEX_RETENTION
    ).delete()
    if deleted_count:  # pragma: no branch
        logger.info(f"Cleaned up {deleted_count} expired mutexes.")

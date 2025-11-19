from django.conf import settings
from django.db.models.functions import Now
from loguru import logger

from app.infra.services import scheduler
from app.verikit.models import EmailVerification


@scheduler.scheduled_job("cron", hour="*/6", jitter=120)
def cleanup_expired_verifications() -> None:
    deleted_count, _ = EmailVerification.objects.filter(
        create_time__lt=Now() - settings.VERIKIT_VERIFICATION_RETENTION
    ).delete()
    if deleted_count:  # pragma: no branch
        logger.info(f"Cleaned up {deleted_count} expired email verifications.")

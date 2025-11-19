from django.conf import settings
from django.db.models.functions import Now
from loguru import logger

from app.core.models import PasswordResetToken
from app.infra.services import scheduler


@scheduler.scheduled_job("cron", hour="*/6", jitter=120)
def cleanup_expired_password_reset_tokens() -> None:
    deleted_count, _ = PasswordResetToken.objects.filter(
        create_time__lt=Now() - settings.PASSWORD_RESET_TOKEN_RETENTION
    ).delete()
    if deleted_count:  # pragma: no branch
        logger.info(f"Cleaned up {deleted_count} expired password reset tokens.")

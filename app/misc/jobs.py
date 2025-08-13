from django.core.management import call_command

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

from django.apps import AppConfig
from django.core.checks import register

from app.infra.checks import check_sqlite_transaction_mode


class InfraConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.infra"

    def ready(self) -> None:
        register(check_sqlite_transaction_mode, "infra")

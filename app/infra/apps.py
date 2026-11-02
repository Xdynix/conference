from django.apps import AppConfig


class InfraConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.infra"

    def ready(self) -> None:
        from app.infra import checks  # noqa: F401

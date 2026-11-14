from django.apps import AppConfig


class InfraConfig(AppConfig):
    name = "app.infra"

    def ready(self) -> None:
        from app.infra import checks  # noqa: F401

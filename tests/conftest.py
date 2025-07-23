import pytest
from django.apps import apps
from django.conf import LazySettings
from django.db import models
from django.utils import timezone
from loguru import logger

from app.settings import LOG_HANDLERS


@pytest.fixture(autouse=True, scope="session")
def disable_file_logger() -> None:
    logger.remove(LOG_HANDLERS.file_logger)


@pytest.fixture(autouse=True, scope="session")
def editable_auto_now_add_field() -> None:
    model: type[models.Model]
    for model in apps.get_models():
        for field in model._meta.fields:
            if not isinstance(field, models.DateTimeField):
                continue
            if not field.auto_now_add:
                continue
            field.auto_now_add = False
            field.default = timezone.now


@pytest.fixture(autouse=True)
def weak_password_hasher(settings: LazySettings) -> None:
    # Use weak password hasher in testing to increase speed.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def disable_serve_static(settings: LazySettings) -> None:
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "servestatic.middleware.ServeStaticMiddleware"
    ]

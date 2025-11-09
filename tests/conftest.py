from functools import partial
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.apps import apps
from django.conf import LazySettings
from django.db import models
from django.test import Client
from django.utils import timezone
from pytest_mock import MockerFixture

from app.ninja.core import AppNinjaAPI


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


@pytest.fixture
def api() -> AppNinjaAPI:
    """``AppNinjaAPI`` instance for testing.

    Creates an API instance with the same configuration as production but uses a unique
    URL namespace to avoid conflicts when registering test routes alongside the main
    application routes.
    """
    return AppNinjaAPI.build(urls_namespace=f"test-{uuid4().hex}")


@pytest.fixture
def api_client(client: Client) -> Client:
    for method in ("post", "put", "patch", "delete"):
        func = getattr(client, method)
        setattr(client, method, partial(func, content_type="application/json"))
    return client


@pytest.fixture
def mock_cf_turnstile(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "app.utils.cf_turnstile.decorators.check_cf_turnstile_response",
        return_value=None,
    )

from http import HTTPStatus
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from faker import Faker

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize("deny_unauthorized", [True, False])
@pytest.mark.parametrize(
    ("has_permission", "user_attrs"),
    [
        (True, {"is_superuser": True}),
        (False, {}),
        (False, {"is_staff": True}),
        (False, {"is_active": False, "is_superuser": True}),
    ],
)
def test_admin_site_superuser_only(
    faker: Faker,
    settings: LazySettings,
    client: Client,
    deny_unauthorized: bool,
    has_permission: bool,
    user_attrs: dict[str, Any],
) -> None:
    settings.ADMIN_LOGIN_DENY_UNAUTHORIZED = deny_unauthorized
    user = User.objects.create_user(username=faker.user_name(), **user_attrs)
    client.force_login(user)

    response = client.get(reverse("admin:index"), follow=False)
    if has_permission:
        assert response.status_code == HTTPStatus.OK
    elif deny_unauthorized:
        assert response.status_code == HTTPStatus.FORBIDDEN
    else:
        assert response.status_code == HTTPStatus.FOUND


@pytest.mark.parametrize("deny_unauthorized", [True, False])
def test_admin_login_denied_when_configured(
    settings: LazySettings,
    client: Client,
    deny_unauthorized: bool,
) -> None:
    settings.ADMIN_LOGIN_DENY_UNAUTHORIZED = deny_unauthorized

    response = client.get(reverse("admin:login"), follow=False)
    if deny_unauthorized:
        assert response.status_code == HTTPStatus.FORBIDDEN
    else:
        assert response.status_code == HTTPStatus.OK

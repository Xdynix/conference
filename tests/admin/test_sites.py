from http import HTTPStatus
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from faker import Faker

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "has_permission, user_attrs",
    [
        (True, {"is_superuser": True}),
        (False, {}),
        (False, {"is_staff": True}),
        (False, {"is_active": False, "is_superuser": True}),
    ],
)
def test_admin_site_superuser_only(
    faker: Faker,
    client: Client,
    has_permission: bool,
    user_attrs: dict[str, Any],
) -> None:
    user = User.objects.create_user(username=faker.user_name(), **user_attrs)
    client.force_login(user)

    response = client.get(reverse("admin:index"), follow=False)
    if has_permission:
        assert response.status_code == HTTPStatus.OK
    else:
        assert response.status_code == HTTPStatus.FOUND

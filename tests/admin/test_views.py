from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from faker import Faker

User = get_user_model()


@pytest.fixture
def media_file(media_root: Path) -> Path:
    file = media_root / "test.txt"
    file.write_text("test content")
    return file


@pytest.mark.django_db
class TestMedia:
    def test_happy_path(
        self,
        faker: Faker,
        client: Client,
        media_file: Path,  # noqa: ARG002
    ) -> None:
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.get("/media/test.txt")

        assert response.status_code == HTTPStatus.OK
        assert b"".join(response.streaming_content) == b"test content"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "user_attrs",
        [
            {},
            {"is_staff": True},
            {"is_active": False, "is_superuser": True},
        ],
    )
    def test_non_superuser_redirects_to_admin_login(
        self,
        faker: Faker,
        client: Client,
        media_file: Path,  # noqa: ARG002
        user_attrs: dict[str, Any],
    ) -> None:
        user = User.objects.create_user(username=faker.user_name(), **user_attrs)
        client.force_login(user)

        response = client.get("/media/test.txt", follow=False)

        assert response.status_code == HTTPStatus.FOUND
        assert "/admin/login/" in response.url  # type: ignore[attr-defined]

    def test_unauthenticated_redirects_to_admin_login(
        self,
        client: Client,
        media_file: Path,  # noqa: ARG002
    ) -> None:
        response = client.get("/media/test.txt", follow=False)

        assert response.status_code == HTTPStatus.FOUND
        assert "/admin/login/" in response.url  # type: ignore[attr-defined]

    def test_path_traversal_forbidden(
        self,
        faker: Faker,
        client: Client,
        media_root: Path,  # noqa: ARG002
    ) -> None:
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.get("/media/../etc/passwd")

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_file_not_found(
        self,
        faker: Faker,
        client: Client,
        media_root: Path,  # noqa: ARG002
    ) -> None:
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.get("/media/nonexistent.txt")

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_directory_not_served(
        self,
        faker: Faker,
        client: Client,
        media_root: Path,
    ) -> None:
        subdir = media_root / "subdir"
        subdir.mkdir()
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.get("/media/subdir")

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_non_get_method_not_allowed(
        self,
        faker: Faker,
        client: Client,
        media_file: Path,  # noqa: ARG002
    ) -> None:
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.post("/media/test.txt")

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_nested_file_served(
        self,
        faker: Faker,
        client: Client,
        media_root: Path,
    ) -> None:
        nested_file = media_root / "uploads" / "2024" / "document.pdf"
        nested_file.parent.mkdir(parents=True, exist_ok=True)
        nested_file.write_bytes(b"PDF content")
        user = User.objects.create_user(username=faker.user_name(), is_superuser=True)
        client.force_login(user)

        response = client.get("/media/uploads/2024/document.pdf")

        assert response.status_code == HTTPStatus.OK
        assert b"".join(response.streaming_content) == b"PDF content"  # type: ignore[attr-defined]

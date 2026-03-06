from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from app.conference.api.doc import DOCS
from app.conference.models import Conference
from app.core.models import User


@pytest.mark.django_db
class TestGetDoc:
    @classmethod
    def path(cls, conference_name: str, doc_name: str) -> str:
        return reverse("api-1.0.0:get-doc", args=[conference_name, doc_name])

    @pytest.mark.parametrize(("doc_name", "relative_path"), DOCS.items())
    def test_returns_raw_markdown(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
        doc_name: str,
        relative_path: str,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, doc_name))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/markdown; charset=utf-8"

        file_path = settings.BASE_DIR / relative_path
        assert file_path.is_file()
        assert response.content.decode() == file_path.read_text(encoding="utf-8")

    def test_unknown_doc_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated_returns_401(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

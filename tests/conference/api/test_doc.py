from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.api.doc import DOCS
from app.conference.models import Conference, Track, TrackRole, TrackRoleAssignment
from app.core.models import User


@pytest.mark.django_db
class TestGetDoc:
    @classmethod
    def path(cls, conference_name: str, doc_name: str) -> str:
        return reverse("api-1.0.0:get-doc", args=[conference_name, doc_name])

    def test_returns_raw_markdown(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/markdown; charset=utf-8"

        expected = (settings.BASE_DIR / "docs/batch-import-api-guide.md").read_text(
            encoding="utf-8"
        )
        assert response.content.decode() == expected

    def test_unknown_doc_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated_returns_401(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_user_without_roles_returns_403(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_admin(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.OK

    def test_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        track_chair = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track, user=track_chair, role=TrackRole.CHAIR
        )
        api_client.force_login(track_chair)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.OK

    def test_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.OK

    def test_global_read_all(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.OK

    def test_conference_reviewer_returns_403(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.path(conference.name, "batch-import-guide"))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("relative_path", DOCS.values())
def test_docs_paths_exist(relative_path: str) -> None:
    assert (settings.BASE_DIR / relative_path).is_file()

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from app.conference.models import Conference, Paper, PaperState, Track
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestListRegistrablePapers:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-registrable-papers", args=[conference_name])

    @pytest.fixture(autouse=True)
    def enable_registration(self, conference: Conference) -> None:
        update_object(conference, registration_enabled=True)

    @pytest.fixture
    def accepted_paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="A-001",
            title="Accepted Paper",
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,  # noqa: ARG002
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "code": "A-001",
                "title": "Accepted Paper",
            },
        ]

    def test_includes_accepted_revision_needed(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,
    ) -> None:
        update_object(
            accepted_paper,
            code="A-002",
            title="Needs Revision",
            state=PaperState.ACCEPTED_REVISION_NEEDED,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "code": "A-002",
                "title": "Needs Revision",
            },
        ]

    def test_returns_empty_when_registration_disabled(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,  # noqa: ARG002
    ) -> None:
        update_object(conference, registration_enabled=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_returns_empty_when_no_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_excludes_unannounced_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,
    ) -> None:
        update_object(accepted_paper, announce_time=None)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_excludes_rejected_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,
    ) -> None:
        update_object(accepted_paper, state=PaperState.REJECTED)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_excludes_deleted_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,
    ) -> None:
        update_object(accepted_paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_excludes_withdrawn_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        accepted_paper: Paper,
    ) -> None:
        update_object(accepted_paper, withdraw_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("non-existent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

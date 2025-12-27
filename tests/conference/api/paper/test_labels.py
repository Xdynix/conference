from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import Conference, Paper, PaperLabel, Track
from app.conference.services import PaperService
from app.core.models import User


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.fixture
def paper_service_set_labels(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "set_paper_labels")


@pytest.mark.django_db
class TestUpdatePaperLabels:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:update-paper-labels",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
        paper_service_set_labels: MagicMock,
    ) -> None:
        PaperLabel.objects.create(paper=paper, key="env", value="prod")
        api_client.force_login(global_admin)

        response = api_client.put(
            self.path(conference.name, paper.code),
            data={"env": "staging", "tier": "frontend"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["labels"] == {"env": "staging", "tier": "frontend"}
        assert not paper.labels.filter(key="env", value="prod").exists()

        paper_service_set_labels.assert_called_once_with(
            paper=paper,
            env="staging",
            tier="frontend",
        )

    def test_empty_payload_clears_labels(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        PaperLabel.objects.create(paper=paper, key="env", value="prod")
        PaperLabel.objects.create(paper=paper, key="tier", value="frontend")
        api_client.force_login(conference_chair)

        response = api_client.put(self.path(conference.name, paper.code), data={})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["labels"] == {}
        assert not paper.labels.exists()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.put(
            self.path(conference.name, paper.code),
            data={"env": "prod"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.put(
            self.path(conference.name, paper.code),
            data={"env": "prod"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_conference_non_admin_forbidden(
        self,
        api_client: Client,
        conference_reviewer: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.put(
            self.path(conference.name, paper.code),
            data={"env": "prod"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_paper_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.put(
            self.path(conference.name, "MISSING-PAPER"),
            data={"env": "prod"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

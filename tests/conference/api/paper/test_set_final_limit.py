from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture

from app.conference.models import Conference, Paper, PaperState, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperWithdrawnError
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
        final_revision_limit=1,
    )


@pytest.fixture
def paper_service_set_limit(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "set_final_revision_limit")


@pytest.mark.django_db
class TestSetPaperFinalLimit:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:set-paper-final-limit",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["final_revision_limit"] == 5

        paper_service_set_limit.assert_called_once_with(
            paper=paper,
            count=5,
        )

    def test_handles_paper_withdrawn_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        paper_service_set_limit.side_effect = PaperWithdrawnError(
            "Cannot modify final revision limit for withdrawn papers."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "withdrawn papers" in response.json()["message"]

    def test_validates_count_required(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_validates_count_non_negative(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": -1},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_allows_count_zero(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 0},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_set_limit.assert_called_once_with(paper=paper, count=0)

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        paper_service_set_limit.return_value = paper
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_set_limit.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        paper_service_set_limit.return_value = paper
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_set_limit.assert_called_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
        paper_service_set_limit: MagicMock,
    ) -> None:
        paper_service_set_limit.return_value = paper
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_set_limit.assert_called_once()

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"count": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

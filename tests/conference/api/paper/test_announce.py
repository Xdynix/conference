from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import Conference
from app.conference.services import PaperService
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper_service_announce(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(
        PaperService,
        "announce_papers",
        return_value=["PAPER-001", "PAPER-002"],
    )


@pytest.mark.django_db
class TestAnnouncePapers:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:announce-papers", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001", "PAPER-002", "PAPER-003"]},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == ["PAPER-001", "PAPER-002"]

        paper_service_announce.assert_awaited_once_with(
            conference,
            ["PAPER-001", "PAPER-002", "PAPER-003"],
        )

    def test_empty_codes_list(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        paper_service_announce.return_value = []
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": []},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

        paper_service_announce.assert_awaited_once_with(conference, [])

    def test_defaults_codes_to_empty_list(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        paper_service_announce.return_value = []
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_announce.assert_awaited_once_with(conference, [])

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent"),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        paper_service_announce.assert_not_awaited()

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        paper_service_announce.assert_not_awaited()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper_service_announce: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_announce.assert_awaited_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper_service_announce: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_announce.assert_awaited_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper_service_announce: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_announce.assert_awaited_once()

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name),
            data={"codes": ["PAPER-001"]},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

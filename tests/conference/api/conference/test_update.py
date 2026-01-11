from datetime import date
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import Conference, ConferenceVisibility, Keyword, KeywordSet
from app.conference.services import ConferenceService, KeywordService
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def conference_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ConferenceService, "update_conference")


@pytest.mark.django_db
class TestUpdateConference:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:update-conference", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        keyword_from_set = Keyword.objects.create(text="Security")
        keyword_set = KeywordSet.objects.create(name="sec-suite")
        keyword_set.keywords.set([keyword_from_set])
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "display_name": "Cyber Security Summit",
                "visibility": ConferenceVisibility.PUBLIC,
                "registration_enabled": True,
                "start_date": "2026-09-24",
                "end_date": "2026-09-27",
                "location": "Cagliari, Italy",
                "keywords": [keyword.text],
                "keyword_sets": [keyword_set.name],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == conference.name
        assert data["display_name"] == "Cyber Security Summit"
        assert data["visibility"] == ConferenceVisibility.PUBLIC
        assert data["registration_enabled"] is True
        assert data["start_date"] == "2026-09-24"
        assert data["end_date"] == "2026-09-27"
        assert data["location"] == "Cagliari, Italy"
        assert data["keywords"] == ["AI", "Security"]
        assert data["tracks"] == []

        conference_service_update.assert_called_once_with(
            name=conference.name,
            display_name="Cyber Security Summit",
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=True,
            start_date=date(2026, 9, 24),
            end_date=date(2026, 9, 27),
            location="Cagliari, Italy",
            keywords=[keyword],
            keyword_sets=[keyword_set],
        )

    def test_partial_update(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"display_name": "Updated Name"},
        )
        assert response.status_code == HTTPStatus.OK

        conference_service_update.assert_called_once_with(
            name=conference.name,
            display_name="Updated Name",
            visibility=None,
            registration_enabled=None,
            keywords=None,
            keyword_sets=None,
            start_date=None,
            end_date=None,
            location=None,
        )

    def test_empty_payload(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        conference_service_update.assert_called_once_with(
            name=conference.name,
            display_name=None,
            visibility=None,
            registration_enabled=None,
            keywords=None,
            keyword_sets=None,
            start_date=None,
            end_date=None,
            location=None,
        )

    def test_conference_chair_can_update(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name),
            data={"display_name": "Chair Updated"},
        )
        assert response.status_code == HTTPStatus.OK

        conference_service_update.assert_called_once()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.patch(
            self.path(conference.name),
            data={"display_name": "Unauthorized Update"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        conference_service_update.assert_not_called()

    def test_handle_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        conference_service_update.side_effect = Conference.DoesNotExist
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"display_name": "Updated Name"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_handle_unknown_keywords(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_service_update: MagicMock,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: nonexistent."),
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name),
            data={"keywords": ["nonexistent"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "keywords"]
        assert "Unknown keywords" in error["msg"]

        conference_service_update.assert_not_called()

    def test_handle_unknown_keyword_sets(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_service_update: MagicMock,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_set_names",
            side_effect=ValueError("Unknown keyword sets: nonexistent."),
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name),
            data={"keyword_sets": ["nonexistent"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "keyword_sets"]
        assert "Unknown keyword sets" in error["msg"]

        conference_service_update.assert_not_called()

    def test_update_display_fields(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "start_date": "2026-09-24",
                "end_date": "2026-09-27",
                "location": "Cagliari, Italy",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["start_date"] == "2026-09-24"
        assert data["end_date"] == "2026-09-27"
        assert data["location"] == "Cagliari, Italy"

        conference_service_update.assert_called_once()
        call_kwargs = conference_service_update.call_args.kwargs
        assert call_kwargs["start_date"] == date(2026, 9, 24)
        assert call_kwargs["end_date"] == date(2026, 9, 27)
        assert call_kwargs["location"] == "Cagliari, Italy"

    def test_clear_start_date_with_empty_string(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        update_object(conference, start_date=date(2026, 9, 24))
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"start_date": ""},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "start_date" not in data

        conference_service_update.assert_called_once()
        call_kwargs = conference_service_update.call_args.kwargs
        assert call_kwargs["start_date"] == ""

    def test_clear_end_date_with_empty_string(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        update_object(conference, end_date=date(2026, 9, 27))
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"end_date": ""},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "end_date" not in data

        conference_service_update.assert_called_once()
        call_kwargs = conference_service_update.call_args.kwargs
        assert call_kwargs["end_date"] == ""

    def test_partial_display_field_update(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        update_object(
            conference,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            location="Old Location",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "start_date": "2024-09-24",
                "location": "New Location",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["start_date"] == "2024-09-24"
        assert data["end_date"] == "2025-01-03"
        assert data["location"] == "New Location"

        conference_service_update.assert_called_once()
        call_kwargs = conference_service_update.call_args.kwargs
        assert call_kwargs["start_date"] == date(2024, 9, 24)
        assert call_kwargs["end_date"] is None
        assert call_kwargs["location"] == "New Location"

    def test_rejects_end_date_before_start_date(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_update: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "start_date": "2026-09-27",
                "end_date": "2026-09-24",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "end_date"]
        assert "on or after start date" in error["msg"]

        conference_service_update.assert_not_called()

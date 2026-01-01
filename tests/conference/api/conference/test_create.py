from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import (
    ConferenceVisibility,
    Keyword,
    KeywordSet,
    TrackVisibility,
)
from app.conference.services import ConferenceService, KeywordService
from app.conference.services.conference import ConferenceNameConflict
from app.core.models import User


@pytest.fixture
def conference_service_create(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ConferenceService, "create_conference")


@pytest.mark.django_db
class TestCreateConference:
    path = reverse("api-1.0.0:create-conference")

    def test_happy_path(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        keyword_set = KeywordSet.objects.create(name="security")
        keyword_from_set = Keyword.objects.create(text="Analysis")
        keyword_set.keywords.set([keyword_from_set])
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "sec-conf",
                "display_name": "Security Conf",
                "visibility": ConferenceVisibility.PUBLIC,
                "keywords": [keyword.text],
                "keyword_sets": [keyword_set.name],
                "tracks": [
                    {
                        "display_name": "Research Track",
                        "visibility": TrackVisibility.PUBLIC,
                    },
                    {
                        "display_name": "Operations Track",
                        "visibility": TrackVisibility.ADMIN_ONLY,
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["name"] == "sec-conf"
        assert data["display_name"] == "Security Conf"
        assert data["visibility"] == ConferenceVisibility.PUBLIC
        assert set(data["keywords"]) == {"AI", "Analysis"}
        [track_a, track_b] = data["tracks"]
        assert track_a["display_name"] == "Research Track"
        assert track_a["visibility"] == TrackVisibility.PUBLIC
        assert track_b["display_name"] == "Operations Track"
        assert track_b["visibility"] == TrackVisibility.ADMIN_ONLY

        conference_service_create.assert_called_once()
        call_kwargs = conference_service_create.call_args.kwargs
        assert call_kwargs["name"] == "sec-conf"
        assert call_kwargs["display_name"] == "Security Conf"
        assert call_kwargs["visibility"] == ConferenceVisibility.PUBLIC
        assert list(call_kwargs["keywords"]) == [keyword]
        assert list(call_kwargs["keyword_sets"]) == [keyword_set]
        [call_kwargs_a, call_kwargs_b] = call_kwargs["tracks"]
        assert len(call_kwargs["tracks"]) == 2
        assert call_kwargs_a["display_name"] == "Research Track"
        assert call_kwargs_a["visibility"] == TrackVisibility.PUBLIC
        assert call_kwargs_b["display_name"] == "Operations Track"
        assert call_kwargs_b["visibility"] == TrackVisibility.ADMIN_ONLY

    def test_trims_whitespace_fields(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        keyword = Keyword.objects.create(text="AI")
        keyword_from_set = Keyword.objects.create(text="Security")
        keyword_set = KeywordSet.objects.create(name="defense-suite")
        keyword_set.keywords.set([keyword_from_set])
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "trim-conf",
                "display_name": "  Cyber Defense Summit  ",
                "keywords": ["  AI  "],
                "keyword_sets": ["  defense-suite  "],
                "tracks": [
                    {
                        "display_name": "  Research Track ",
                        "visibility": TrackVisibility.PUBLIC,
                    },
                    {"display_name": " Operations Track  "},
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["display_name"] == "Cyber Defense Summit"
        assert set(data["keywords"]) == {"AI", "Security"}
        assert data["tracks"][0]["display_name"] == "Research Track"
        assert data["tracks"][0]["visibility"] == TrackVisibility.PUBLIC
        assert data["tracks"][1]["display_name"] == "Operations Track"
        assert data["tracks"][1]["visibility"] == TrackVisibility.ADMIN_ONLY

        conference_service_create.assert_called_once()
        call_kwargs = conference_service_create.call_args.kwargs
        assert call_kwargs["display_name"] == "Cyber Defense Summit"
        assert list(call_kwargs["keywords"]) == [keyword]
        assert list(call_kwargs["keyword_sets"]) == [keyword_set]
        assert call_kwargs["tracks"][0]["display_name"] == "Research Track"
        assert call_kwargs["tracks"][1]["display_name"] == "Operations Track"

    def test_minimal_payload_uses_defaults(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "minimal-conf",
                "display_name": "Minimal Conf",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "name": "minimal-conf",
            "display_name": "Minimal Conf",
            "visibility": ConferenceVisibility.ADMIN_ONLY,
            "keywords": [],
            "tracks": [],
        }

        conference_service_create.assert_called_once()
        call_kwargs = conference_service_create.call_args.kwargs
        assert call_kwargs["name"] == "minimal-conf"
        assert call_kwargs["visibility"] == ConferenceVisibility.ADMIN_ONLY
        assert list(call_kwargs["keywords"]) == []
        assert list(call_kwargs["keyword_sets"]) == []
        assert list(call_kwargs["tracks"]) == []

    def test_handle_conference_name_conflict(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        conference_service_create.side_effect = ConferenceNameConflict
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={"name": "dup-conf", "display_name": "New Conf"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "already exists" in response.json()["message"]

        conference_service_create.assert_called_once()

    def test_handle_unknown_keywords(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: nonexistent."),
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "unknown-keyword-conf",
                "display_name": "Unknown Keyword Conf",
                "keywords": ["nonexistent"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "keywords"]
        assert "Unknown keywords" in error["msg"]

        conference_service_create.assert_not_called()

    def test_handle_unknown_keyword_sets(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_set_names",
            side_effect=ValueError("Unknown keyword sets: missing-set."),
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "unknown-keyword-set-conf",
                "display_name": "Unknown Keyword Set Conf",
                "keyword_sets": ["missing-set"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "keyword_sets"]
        assert "Unknown keyword sets" in error["msg"]

        conference_service_create.assert_not_called()

    def test_rejects_whitespace_only_keyword(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path,
            data={
                "name": "whitespace-keyword-conf",
                "display_name": "Whitespace Keyword Conf",
                "keywords": ["   "],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "keywords", 0]
        assert "at least 1" in error["msg"]

        conference_service_create.assert_not_called()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_service_create: MagicMock,
    ) -> None:
        user = User.objects.create_user(username="regular")
        api_client.force_login(user)

        response = api_client.post(
            self.path,
            data={
                "name": "regular-conf",
                "display_name": "Regular Conf",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        conference_service_create.assert_not_called()

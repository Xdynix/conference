from http import HTTPStatus
from typing import Any

import httpx
import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from respx.router import MockRouter
from ulid import ULID

from app.conference.api.conference.ieee_ecopyright import IEEE_ECOPYRIGHT_API_URL
from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    IEEEeCopyrightConfig,
    IEEEeCopyrightConsent,
    Paper,
    Track,
)
from app.core.models import User


@pytest.mark.django_db
class TestGetIEEEeCopyrightConfig:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:get-ieee-ecopyright-config",
            args=[conference_name],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(
            conference=conference,
            display_name="Research Track",
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test Conference Proceedings",
            article_source="TC2024",
        )
        config.exempt_tracks.add(track)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "publication_title": "Test Conference Proceedings",
            "article_source": "TC2024",
            "exempt_tracks": [str(track.uid)],
        }

    def test_returns_empty_exempt_tracks(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test Conference",
            article_source="TC2024",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["exempt_tracks"] == []

    def test_config_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_global_read_all_authorized(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test",
            article_source="TC",
        )
        api_client.force_login(global_read_all)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test",
            article_source="TC",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conf"))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestUpdateIEEEeCopyrightConfig:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:update-ieee-ecopyright-config",
            args=[conference_name],
        )

    def test_create_config(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "New Conference Proceedings",
                "article_source": "NC2024",
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "publication_title": "New Conference Proceedings",
            "article_source": "NC2024",
            "exempt_tracks": [],
        }

        assert IEEEeCopyrightConfig.objects.filter(conference=conference).exists()

    def test_create_with_exempt_tracks(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(
            conference=conference,
            display_name="Workshop Track",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Conference Proceedings",
                "article_source": "CP2024",
                "exempt_tracks": [str(track.uid)],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["exempt_tracks"] == [str(track.uid)]

    def test_create_missing_publication_title(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"article_source": "TC2024"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "publication_title" in response.json()["message"]

    def test_create_missing_article_source(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"publication_title": "Test Conference"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "article_source" in response.json()["message"]

    def test_create_missing_both_required_fields(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        message = response.json()["message"]
        assert "publication_title" in message
        assert "article_source" in message

    def test_update_config(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Original Title",
            article_source="OT2024",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Updated Title",
                "article_source": "UT2024",
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "publication_title": "Updated Title",
            "article_source": "UT2024",
            "exempt_tracks": [],
        }

    def test_partial_update_publication_title_only(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Original Title",
            article_source="OT2024",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"publication_title": "New Title"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["publication_title"] == "New Title"
        assert data["article_source"] == "OT2024"

    def test_partial_update_article_source_only(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Original Title",
            article_source="OT2024",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"article_source": "NS2024"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["publication_title"] == "Original Title"
        assert data["article_source"] == "NS2024"

    def test_empty_payload_keeps_existing(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(
            conference=conference,
            display_name="Track",
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Original Title",
            article_source="OT2024",
        )
        config.exempt_tracks.add(track)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["publication_title"] == "Original Title"
        assert data["article_source"] == "OT2024"
        assert data["exempt_tracks"] == [str(track.uid)]

    def test_update_exempt_tracks(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track_a = Track.objects.create(
            conference=conference,
            display_name="Track A",
        )
        track_b = Track.objects.create(
            conference=conference,
            display_name="Track B",
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        config.exempt_tracks.add(track_a)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"exempt_tracks": [str(track_b.uid)]},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["exempt_tracks"] == [str(track_b.uid)]

    def test_clear_exempt_tracks_with_empty_list(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(
            conference=conference,
            display_name="Track",
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        config.exempt_tracks.add(track)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"exempt_tracks": []},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["exempt_tracks"] == []

    def test_omit_exempt_tracks_keeps_existing(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        track = Track.objects.create(
            conference=conference,
            display_name="Track",
        )
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        config.exempt_tracks.add(track)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"publication_title": "New Title"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["publication_title"] == "New Title"
        assert data["exempt_tracks"] == [str(track.uid)]

    def test_invalid_track_uid_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        invalid_uid = ULID()
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"exempt_tracks": [str(invalid_uid)]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "exempt_tracks"]
        assert str(invalid_uid) in error["msg"]

    def test_track_from_other_conference_rejected(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name="Other Track",
        )
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"exempt_tracks": [str(other_track.uid)]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "exempt_tracks"]
        assert str(other_track.uid) in error["msg"]

    def test_multiple_invalid_tracks_reported(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Title",
            article_source="TC",
        )
        invalid_uid_1 = ULID()
        invalid_uid_2 = ULID()
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name),
            data={"exempt_tracks": [str(invalid_uid_1), str(invalid_uid_2)]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "exempt_tracks"]
        assert str(invalid_uid_1) in error["msg"]
        assert str(invalid_uid_2) in error["msg"]

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Chair Conference",
                "article_source": "CC2024",
            },
        )
        assert response.status_code == HTTPStatus.OK

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Test",
                "article_source": "TC",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Test",
                "article_source": "TC",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Test",
                "article_source": "TC",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "publication_title": "Test",
                "article_source": "TC",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path("nonexistent-conf"),
            data={
                "publication_title": "Test",
                "article_source": "TC",
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.fixture
def ieee_ecopyright_config(conference: Conference) -> IEEEeCopyrightConfig:
    return IEEEeCopyrightConfig.objects.create(
        conference=conference,
        publication_title="Test Conference",
        article_source="TC2024",
    )


@pytest.fixture
def ieee_api_url(ieee_ecopyright_config: IEEEeCopyrightConfig) -> str:
    return IEEE_ECOPYRIGHT_API_URL.format(
        article_source=ieee_ecopyright_config.article_source
    )


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="CONF-001",
        title="Test Paper",
    )


@pytest.mark.django_db
class TestRefreshIEEEeCopyrightConsents:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:refresh-ieee-ecopyright-consents",
            args=[conference_name],
        )

    @classmethod
    def make_ieee_response(
        cls,
        articles: list[dict[str, Any]],
        status: str = "Success",
    ) -> dict[str, Any]:
        return {
            "statusCode": 200,
            "status": status,
            "articlecount": len(articles),
            "articleList": articles,
        }

    @classmethod
    def make_article(
        cls,
        paper_code: str,
        author_email: str = "author@example.com",
    ) -> dict[str, Any]:
        return {
            "ecfPaperId": paper_code,
            "paperTitle": "Test Paper",
            "authorName": "Test Author",
            "authorEmail": author_email,
            "dateOfSignature": "2025-01-01",
            "copyrightType": "IEEE",
        }

    def test_happy_path(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
        paper: Paper,
    ) -> None:
        mock_ieee = respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(
                200,
                json=self.make_ieee_response([self.make_article("CONF-001")]),
            )
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"unmatched_codes": []}
        assert IEEEeCopyrightConsent.objects.filter(paper=paper).exists()
        assert mock_ieee.call_count == 1

    def test_returns_unmatched_codes(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
        paper: Paper,  # noqa: ARG002
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(
                200,
                json=self.make_ieee_response(
                    [
                        self.make_article("CONF-001"),
                        self.make_article("CONF-999"),
                    ]
                ),
            )
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"unmatched_codes": ["CONF-999"]}

    def test_skips_existing_consents(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
        paper: Paper,
    ) -> None:
        IEEEeCopyrightConsent.objects.create(
            paper=paper,
            raw_response={"existing": True},
        )
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(
                200,
                json=self.make_ieee_response([self.make_article("CONF-001")]),
            )
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        consent = IEEEeCopyrightConsent.objects.get(paper=paper)
        assert consent.raw_response == {"existing": True}

    def test_empty_article_list(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(200, json=self.make_ieee_response([]))
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"unmatched_codes": []}

    def test_no_config_bad_request(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_ieee_api_non_200_status(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(return_value=httpx.Response(500))
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_ieee_api_invalid_json(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_ieee_api_non_success_status(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(
                200,
                json=self.make_ieee_response([], status="Error"),
            )
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_ieee_api_connection_error(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_ieee_api_unexpected_format(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "Success",
                    "articleList": [{"missingPaperId": "no ecfPaperId field"}],
                },
            )
        )
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_conference_chair_authorized(
        self,
        respx_mock: MockRouter,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        ieee_api_url: str,
    ) -> None:
        respx_mock.get(ieee_api_url).mock(
            return_value=httpx.Response(200, json=self.make_ieee_response([]))
        )
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path("nonexistent-conf"))
        assert response.status_code == HTTPStatus.NOT_FOUND

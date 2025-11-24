from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    KeywordSet,
)
from app.conference.services import ConferenceService, KeywordService
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def conference_chair(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.fixture
def conference_secretary(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.SECRETARY,
    )
    return user


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
                "visibility": Conference.Visibility.PUBLIC,
                "keywords": [keyword.text],
                "keyword_sets": [keyword_set.name],
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["name"] == conference.name
        assert response.json()["display_name"] == "Cyber Security Summit"
        assert response.json()["visibility"] == Conference.Visibility.PUBLIC
        assert set(response.json()["keywords"]) == {"AI", "Security"}
        assert response.json()["tracks"] == []

        conference_service_update.assert_called_once_with(
            name=conference.name,
            display_name="Cyber Security Summit",
            visibility=Conference.Visibility.PUBLIC,
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
            keywords=None,
            keyword_sets=None,
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
            keywords=None,
            keyword_sets=None,
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

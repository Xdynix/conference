from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    UserConferenceProfile,
)
from app.conference.services import UserConferenceProfileService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


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
        visibility=Conference.Visibility.PUBLIC,
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
def conference_reviewer(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.REVIEWER,
    )
    return user


@pytest.fixture
def profile_service_get_or_create(mocker: MockerFixture) -> AsyncMock:
    return mocker.spy(UserConferenceProfileService, "get_or_create_profile")


@pytest.fixture
def profile_service_update(mocker: MockerFixture) -> AsyncMock:
    return mocker.spy(UserConferenceProfileService, "update_profile")


@pytest.mark.django_db
class TestGetCurrentUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:get-current-user-conference-profile",
            args=[conference_name],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        profile = UserConferenceProfile.objects.create(
            user=user,
            conference=conference,
            desired_paper_count=9,
        )
        keyword = Keyword.objects.create(text="AI")
        profile.interested_keywords.add(keyword)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "desired_paper_count": 9,
            "interested_keywords": ["AI"],
        }

        profile_service_get_or_create.assert_awaited_once()

    def test_private_conference_returns_404(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.ADMIN_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

        profile_service_get_or_create.assert_not_called()

    def test_unauthenticated_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        profile_service_get_or_create.assert_not_called()


@pytest.mark.django_db
class TestGetUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str, user_id: ULID) -> str:
        return reverse(
            "api-1.0.0:get-user-conference-profile",
            args=[conference_name, user_id],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        profile = UserConferenceProfile.objects.create(
            user=user,
            conference=conference,
            desired_paper_count=2,
        )
        keyword = Keyword.objects.create(text="systems")
        profile.interested_keywords.add(keyword)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, user.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "desired_paper_count": 2,
            "interested_keywords": ["systems"],
        }

        profile_service_get_or_create.assert_awaited_once()

    def test_conference_chair_can_access(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_chair: User,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, user.uid))
        assert response.status_code == HTTPStatus.OK

        profile_service_get_or_create.assert_awaited_once()

    def test_inactive_conference_returns_404(
        self,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, user.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        profile_service_get_or_create.assert_not_called()

    def test_inactive_user_returns_404(
        self,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, user.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        profile_service_get_or_create.assert_not_called()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_reviewer: User,
        profile_service_get_or_create: AsyncMock,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.path(conference.name, user.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

        profile_service_get_or_create.assert_not_called()


@pytest.mark.django_db
class TestUpdateCurrentUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:update-current-user-conference-profile",
            args=[conference_name],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
        profile_service_update: AsyncMock,
    ) -> None:
        Keyword.objects.create(text="ML")
        existing = Keyword.objects.create(text="AI")
        profile = UserConferenceProfile.objects.create(
            user=user,
            conference=conference,
            desired_paper_count=8,
        )
        profile.interested_keywords.add(existing)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={
                "desired_paper_count": 3,
                "interested_keywords": ["ML"],
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "desired_paper_count": 3,
            "interested_keywords": ["ML"],
        }

        profile_service_get_or_create.assert_awaited_once()
        profile_service_update.assert_awaited_once_with(
            profile=profile,
            desired_paper_count=3,
            interested_keywords=["ML"],
        )

    def test_empty_payload(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        profile_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        profile_service_update.assert_not_called()

    def test_handle_value_error(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        profile_service_update: AsyncMock,
    ) -> None:
        profile_service_update.side_effect = ValueError("Unknown keywords: invalid")
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={"interested_keywords": ["invalid"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "interested_keywords"]
        assert "Unknown keywords" in error["msg"]

    def test_unauthenticated_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        profile_service_update: AsyncMock,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name),
            data={"desired_paper_count": 7},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        profile_service_update.assert_not_called()


@pytest.mark.django_db
class TestUpdateUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str, user_id: ULID) -> str:
        return reverse(
            "api-1.0.0:update-user-conference-profile",
            args=[conference_name, user_id],
        )

    def test_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_get_or_create: AsyncMock,
        profile_service_update: AsyncMock,
    ) -> None:
        Keyword.objects.create(text="Security")
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, user.uid),
            data={
                "desired_paper_count": 6,
                "interested_keywords": ["Security"],
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "desired_paper_count": 6,
            "interested_keywords": ["Security"],
        }

        profile_service_get_or_create.assert_awaited_once()
        profile_service_update.assert_awaited_once_with(
            profile=mocker.ANY,
            desired_paper_count=6,
            interested_keywords=["Security"],
        )

    def test_conference_chair_can_update_profile(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_chair: User,
        profile_service_update: AsyncMock,
    ) -> None:
        Keyword.objects.create(text="cloud")
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, user.uid),
            data={"interested_keywords": ["cloud"]},
        )
        assert response.status_code == HTTPStatus.OK

        profile_service_update.assert_awaited_once()

    def test_empty_payload(
        self,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, user.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        profile_service_update.assert_not_called()

    def test_handle_value_error(
        self,
        api_client: Client,
        user: User,
        global_admin: User,
        conference: Conference,
        profile_service_update: AsyncMock,
    ) -> None:
        profile_service_update.side_effect = ValueError("Validation failed")
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, user.uid),
            data={"interested_keywords": ["invalid"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "interested_keywords"]
        assert "Validation failed" in error["msg"]

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_reviewer: User,
        profile_service_update: AsyncMock,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.patch(
            self.path(conference.name, user.uid),
            data={"desired_paper_count": 9},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        profile_service_update.assert_not_called()

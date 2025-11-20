from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    UserConferenceProfile,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=Conference.Visibility.PUBLIC,
    )


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def conference_admin(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.mark.django_db
class TestGetCurrentUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:get-current-user-conference-profile",
            args=[conference_name],
        )

    def test_returns_existing_profile(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
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

    def test_creates_profile_when_missing(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "desired_paper_count": 5,
            "interested_keywords": [],
        }

        profile = UserConferenceProfile.objects.get(
            user=user,
            conference=conference,
        )
        assert profile.desired_paper_count == 5
        assert not profile.interested_keywords.exists()

    def test_private_conference_returns_404(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.ADMIN_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestGetUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str, user_id: ULID) -> str:
        return reverse(
            "api-1.0.0:get-user-conference-profile",
            args=[conference_name, user_id],
        )

    @pytest.fixture
    def profile_user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    def test_global_admin_creates_profile(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "desired_paper_count": 5,
            "interested_keywords": [],
        }
        assert UserConferenceProfile.objects.filter(
            user=profile_user,
            conference=conference,
        ).exists()

    def test_returns_existing_profile(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        profile = UserConferenceProfile.objects.create(
            user=profile_user,
            conference=conference,
            desired_paper_count=2,
        )
        keyword = Keyword.objects.create(text="systems")
        profile.interested_keywords.add(keyword)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "desired_paper_count": 2,
            "interested_keywords": ["systems"],
        }

    def test_conference_admin_can_access(
        self,
        api_client: Client,
        conference_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.OK

    def test_inactive_conference_returns_404(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_user_returns_404(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        update_object(profile_user, is_active=False)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
        profile_user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, profile_user.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestUpdateCurrentUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse(
            "api-1.0.0:update-current-user-conference-profile",
            args=[conference_name],
        )

    def test_updates_profile(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
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

        profile.refresh_from_db()
        assert profile.desired_paper_count == 3
        assert list(profile.interested_keywords.values_list("text", flat=True)) == [
            "ML"
        ]

    def test_rejects_unknown_keyword(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name),
            data={"interested_keywords": ["missing"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_unauthenticated_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name),
            data={"desired_paper_count": 7},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUpdateUserConferenceProfile:
    @classmethod
    def path(cls, conference_name: str, user_id: ULID) -> str:
        return reverse(
            "api-1.0.0:update-user-conference-profile",
            args=[conference_name, user_id],
        )

    @pytest.fixture
    def profile_user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    def test_global_admin_updates_profile(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        Keyword.objects.create(text="Security")
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, profile_user.uid),
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

        profile = UserConferenceProfile.objects.get(
            user=profile_user,
            conference=conference,
        )
        assert profile.desired_paper_count == 6
        assert list(profile.interested_keywords.values_list("text", flat=True)) == [
            "Security"
        ]

    def test_conference_admin_updates_profile(
        self,
        api_client: Client,
        conference_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        Keyword.objects.create(text="cloud")
        api_client.force_login(conference_admin)

        response = api_client.patch(
            self.path(conference.name, profile_user.uid),
            data={"interested_keywords": ["cloud"]},
        )
        assert response.status_code == HTTPStatus.OK

    def test_rejects_unknown_keyword(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        profile_user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, profile_user.uid),
            data={"interested_keywords": ["unknown"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
        profile_user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, profile_user.uid),
            data={"desired_paper_count": 9},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

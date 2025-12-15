from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Profile,
)
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
        visibility=Conference.Visibility.PUBLIC,
    )


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
class TestLookupRoleAssignmentUser:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:lookup-role-assignment-user", args=[conference_name])

    def test_happy_path_with_profile(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email="alice@example.com",
        )
        Profile.objects.create(
            user=user,
            given_name="Alice",
            family_name="Smith",
            affiliation="Example University",
            region_code="US",
        )
        api_client.force_login(conference_admin)

        response = api_client.get(
            self.path(conference.name),
            data={"email": "ALICE@example.com"},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(user.uid),
            "username": user.username,
            "email": user.email,
            "managed": False,
            "profile": {
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "Example University",
                "region_code": "US",
            },
        }

    def test_user_not_found(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(
            self.path(conference.name),
            data={"email": "missing@example.com"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_profile_absent_omitted(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        global_admin: User,
    ) -> None:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        api_client.force_login(global_admin)

        response = api_client.get(
            self.path(conference.name),
            data={"email": user.email},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(user.uid),
            "username": user.username,
            "email": user.email,
            "managed": False,
        }

    def test_auth_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(
            self.path(conference.name),
            data={"email": "someone@example.com"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_auth_forbidden_without_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(
            self.path(conference.name),
            data={"email": "someone@example.com"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

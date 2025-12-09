from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import (
    CodePool,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import approx_now


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
def global_read_all(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
    return user


@pytest.fixture
def conference_chair(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.mark.django_db
class TestListCodePools:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-code-pools", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool_b = CodePool.objects.create(
            conference=conference,
            name="Workshop Pool",
            prefix="WS",
        )
        pool_a = CodePool.objects.create(
            conference=conference,
            name="Main Pool",
            prefix="CONF",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(pool_a.uid),
                "name": "Main Pool",
                "prefix": "CONF",
                "next_sequence": 1,
                "create_time": approx_now(),
                "update_time": approx_now(),
            },
            {
                "uid": str(pool_b.uid),
                "name": "Workshop Pool",
                "prefix": "WS",
                "next_sequence": 1,
                "create_time": approx_now(),
                "update_time": approx_now(),
            },
        ]

    def test_returns_empty_list_when_no_pools(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_scopes_pools_to_conference(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        pool = CodePool.objects.create(
            conference=conference,
            name="Target Pool",
            prefix="TGT",
        )
        CodePool.objects.create(
            conference=other_conference,
            name="Other Pool",
            prefix="OTH",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [pool_data] = data
        assert pool_data["uid"] == str(pool.uid)

    def test_global_read_all_authorized(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_chair_of_other_conference_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
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

    def test_unauthenticated_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
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

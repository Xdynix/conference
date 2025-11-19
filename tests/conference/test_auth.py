from http import HTTPStatus
from typing import Any

import pytest
from django.test import Client
from faker import Faker
from ninja import NinjaAPI

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
)
from app.core.models import User
from app.core.types import HttpRequest
from tests.base import URLConfTestCase, URLPatterns
from tests.helpers import any_str, update_object


@pytest.mark.django_db
class ConferenceAuthTestCase(URLConfTestCase):
    auth = has_any_conference_roles(ConferenceRole.CHAIR)
    path_template = "/conferences/{conference_name}/protected"

    @classmethod
    def path(cls, conference: Conference) -> str:
        return cls.path_template.format(conference_name=conference.name)

    @classmethod
    def assert_response_is_ok(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.OK
        assert response.json() == "OK"

    @classmethod
    def assert_response_is_forbidden(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": any_str}

    @classmethod
    def assert_response_is_unauthorized(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": any_str}

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get(self.path_template, auth=self.auth)
        async def view(request: HttpRequest, conference_name: str) -> str:  # noqa: ARG001
            return "OK"

        # Intentionally imported as local to prevent it
        # from occupying the global namespace.
        from django.urls import path

        return [path("", api.urls)]

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )


class TestHasAnyConferenceRolesSingle(ConferenceAuthTestCase):
    def test_unauthenticated_denied(
        self,
        client: Client,
        conference: Conference,
    ) -> None:
        response = client.get(self.path(conference))
        self.assert_response_is_unauthorized(response)

    def test_private_conference_without_assignment_hidden(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        client.force_login(user)
        response = client.get(self.path(conference))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_public_conference_without_assignment_forbidden(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.PUBLIC)
        client.force_login(user)
        response = client.get(self.path(conference))
        self.assert_response_is_forbidden(response)

    def test_superuser_allowed(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(user, is_superuser=True)
        client.force_login(user)
        response = client.get(self.path(conference))
        self.assert_response_is_ok(response)

    def test_allows_matching_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)
        response = client.get(self.path(conference))
        self.assert_response_is_ok(response)

    def test_missing_conference_not_found(
        self,
        faker: Faker,
        client: Client,
        user: User,
    ) -> None:
        phantom = Conference(name=faker.slug())
        client.force_login(user)
        response = client.get(self.path(phantom))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        update_object(conference, active=False)
        client.force_login(user)
        response = client.get(self.path(conference))
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestHasAnyConferenceRolesMulti(ConferenceAuthTestCase):
    auth = has_any_conference_roles(ConferenceRole.CHAIR, ConferenceRole.SECRETARY)

    def test_allows_any_specified_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        client.force_login(user)
        response = client.get(self.path(conference))
        self.assert_response_is_ok(response)

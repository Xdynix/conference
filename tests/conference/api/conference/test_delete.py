from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import Conference, ConferenceRole, ConferenceRoleAssignment
from app.conference.services import ConferenceService
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
def conference_service_deactivate(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ConferenceService, "deactivate_conference")


@pytest.mark.django_db
class TestDeleteConference:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:delete-conference", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_deactivate: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

        conference_service_deactivate.assert_called_once_with(name=conference.name)

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        conference_service_deactivate: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

        conference_service_deactivate.assert_not_called()

    def test_handle_does_not_exist(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_service_deactivate: MagicMock,
    ) -> None:
        conference_service_deactivate.side_effect = Conference.DoesNotExist
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

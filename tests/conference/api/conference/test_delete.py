from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import Conference
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestDeleteConference:
    @staticmethod
    def path(conference_name: str) -> str:
        return reverse(
            "api-1.0.0:delete-conference",
            kwargs={"conference_name": conference_name},
        )

    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def authorized_user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

        conference.refresh_from_db()
        assert conference.active is False

    def test_missing_conference_returns_404(
        self,
        api_client: Client,
        authorized_user: User,
    ) -> None:
        api_client.force_login(authorized_user)

        response = api_client.delete(self.path("missing-conf"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        authorized_user: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(authorized_user)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

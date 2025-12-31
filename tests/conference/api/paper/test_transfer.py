from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import User
from tests.helpers import any_str, update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.fixture
def new_owner(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


@pytest.mark.django_db
class TestTransferPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:transfer-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["owner"]["uid"] == str(new_owner.uid)

        paper.refresh_from_db()
        assert paper.owner_id == new_owner.pk

    def test_email_case_insensitive(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email.upper()},
        )
        assert response.status_code == HTTPStatus.OK

        paper.refresh_from_db()
        assert paper.owner_id == new_owner.pk

    def test_user_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": "nonexistent@example.com"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "new_owner_email"]
        assert error["msg"] == "User not found."

    def test_inactive_user_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        update_object(new_owner, is_active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["msg"] == "User not found."

    def test_invalid_email_format(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": "not-an-email"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "new_owner_email"]
        assert error["msg"] == any_str

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        new_owner: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        new_owner: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent-conference", "PAPER-001"),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        new_owner: User,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        new_owner: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        new_owner: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", list(TrackRole))
    def test_authorization_track_roles_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        new_owner: User,
        track_role: TrackRole,
    ) -> None:
        track_user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_user,
            role=track_role,
        )
        api_client.force_login(track_user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "non_chair_role",
        [role for role in ConferenceRole if role != ConferenceRole.CHAIR],
    )
    def test_authorization_conference_non_chair_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        new_owner: User,
        non_chair_role: ConferenceRole,
    ) -> None:
        non_chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_chair,
            role=non_chair_role,
        )
        api_client.force_login(non_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"new_owner_email": new_owner.email},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

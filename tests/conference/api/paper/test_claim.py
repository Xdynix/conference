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
    Paper,
    PaperAuthor,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ClaimService
from app.conference.services.claim import ClaimConflictError
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    paper = Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )
    PaperAuthor.objects.create(
        paper=paper,
        given_name="Alice",
        family_name="Smith",
        email="alice@example.com",
        corresponding=True,
    )
    return paper


@pytest.fixture
def claim_service_set(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ClaimService, "set_claim")


@pytest.fixture
def claim_service_remove(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ClaimService, "remove_claim")


@pytest.mark.django_db
class TestSetPaperClaim:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:set-paper-claim", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        claim_service_set: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["claim_email"] == "alice@example.com"

        claim_service_set.assert_called_once_with(paper=paper)

    def test_value_error_returns_400(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        claim_service_set: MagicMock,
    ) -> None:
        claim_service_set.side_effect = ValueError(
            "Paper must have exactly one corresponding author."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        data = response.json()
        assert "corresponding author" in data["message"]

    def test_claim_conflict_returns_409(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        claim_service_set: MagicMock,
    ) -> None:
        claim_service_set.side_effect = ClaimConflictError(
            "Paper authors were modified concurrently."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.CONFLICT

    def test_paper_does_not_exist_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        claim_service_set: MagicMock,
    ) -> None:
        claim_service_set.side_effect = Paper.DoesNotExist()
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        claim_service_set: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        claim_service_set.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        claim_service_set: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        claim_service_set.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        claim_service_set: MagicMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        claim_service_set.assert_called_once()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_authorization_track_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestRemovePaperClaim:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:remove-paper-claim",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        claim_service_remove: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        claim_service_remove.assert_called_once_with(paper=paper)

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        claim_service_remove: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        claim_service_remove.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        claim_service_remove: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        claim_service_remove.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        claim_service_remove: MagicMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        claim_service_remove.assert_called_once()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_authorization_track_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

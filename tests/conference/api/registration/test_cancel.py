from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Paper,
    PaperState,
    Registration,
    RegistrationState,
    RegistrationTitle,
    Track,
)
from app.conference.services import RegistrationService
from app.conference.services.registration import InvalidRegistrationStateError
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import update_object


@pytest.fixture
def paper_required_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
        admin_only=False,
        paper_required=True,
    )


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
    )


@pytest.fixture
def registration(
    faker: Faker,
    conference: Conference,
    user: User,
    paper: Paper,
    paper_required_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=paper,
        attendance_type=paper_required_type,
        state=RegistrationState.PENDING,
        receipt_title="Test University",
        title=RegistrationTitle.DR,
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation="Test Affiliation",
        region_code=Region.US.name,
        email=faker.email(),
        phone=faker.phone_number(),
        self_introduction="Test introduction.",
    )


@pytest.fixture
def registration_service_cancel(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(RegistrationService, "cancel_registration")


@pytest.mark.django_db
class TestCancelMyRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:cancel-my-registration",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_cancel: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == RegistrationState.CANCELLED
        assert data["uid"] == str(registration.uid)

        registration_service_cancel.assert_called_once_with(
            registration,
            mode="author",
        )

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_cancel: MagicMock,
    ) -> None:
        registration_service_cancel.side_effect = InvalidRegistrationStateError(
            "Only pending registrations can be cancelled."
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "pending registrations" in response.json()["message"]

    def test_registration_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_belongs_to_different_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(registration, user=other_user)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestCancelRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:cancel-registration",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        registration: Registration,
        registration_service_cancel: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == RegistrationState.CANCELLED
        assert data["uid"] == str(registration.uid)
        assert data["user"]["uid"] == str(user.uid)

        registration_service_cancel.assert_called_once_with(
            registration,
            mode="admin",
        )

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        registration_service_cancel: MagicMock,
    ) -> None:
        registration_service_cancel.side_effect = InvalidRegistrationStateError(
            "Registration is already cancelled."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "already cancelled" in response.json()["message"]

    def test_registration_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        registration: Registration,
        registration_service_cancel: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        registration_service_cancel.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
        registration_service_cancel: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        registration_service_cancel.assert_called_once()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        non_admin_role: ConferenceRole,
    ) -> None:
        non_admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_admin,
            role=non_admin_role,
        )
        api_client.force_login(non_admin)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        read_all_user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=read_all_user,
            role=GlobalRole.READ_ALL,
        )
        api_client.force_login(read_all_user)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

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
from app.conference.services.registration import (
    AttendanceTypeIncompatibleError,
    InvalidRegistrationStateError,
)
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
def no_paper_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="General Attendance",
        admin_only=False,
        paper_required=False,
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
        receipt_title="Original University",
        title=RegistrationTitle.DR,
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation="Original Affiliation",
        region_code=Region.US.name,
        email=faker.email(),
        phone=faker.phone_number(),
        self_introduction="Original introduction.",
    )


@pytest.fixture
def registration_no_paper(
    faker: Faker,
    conference: Conference,
    user: User,
    no_paper_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=None,
        attendance_type=no_paper_type,
        state=RegistrationState.PENDING,
        receipt_title="Original Company",
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation="Original Company",
        region_code=Region.US.name,
        email=faker.email(),
        phone=faker.phone_number(),
        self_introduction="Industry participant.",
    )


@pytest.fixture
def registration_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(RegistrationService, "update_registration")


@pytest.mark.django_db
class TestUpdateMyRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-my-registration",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={
                "receipt_title": "Updated University",
                "title": RegistrationTitle.PROF,
                "given_name": "Updated",
                "family_name": "Name",
                "affiliation": "Updated Affiliation",
                "region_code": Region.GB.name,
                "email": "updated@example.com",
                "phone": "+1-555-999-0000",
                "self_introduction": "Updated introduction.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["receipt_title"] == "Updated University"
        assert data["title"] == RegistrationTitle.PROF
        assert data["given_name"] == "Updated"
        assert data["family_name"] == "Name"
        assert data["affiliation"] == "Updated Affiliation"
        assert data["region_code"] == Region.GB.name
        assert data["email"] == "updated@example.com"
        assert data["phone"] == "+1-555-999-0000"
        assert data["self_introduction"] == "Updated introduction."

        registration_service_update.assert_called_once_with(
            registration,
            mode="author",
            receipt_title="Updated University",
            title=RegistrationTitle.PROF,
            given_name="Updated",
            family_name="Name",
            affiliation="Updated Affiliation",
            region_code=Region.GB.name,
            email="updated@example.com",
            phone="+1-555-999-0000",
            self_introduction="Updated introduction.",
        )

    def test_partial_update(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        original_email = registration.email
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Partial Update"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["receipt_title"] == "Partial Update"
        assert data["email"] == original_email

        registration_service_update.assert_called_once_with(
            registration,
            mode="author",
            receipt_title="Partial Update",
        )

    def test_empty_payload(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["receipt_title"] == registration.receipt_title

        registration_service_update.assert_called_once_with(
            registration,
            mode="author",
        )

    def test_clear_title_with_empty_string(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"title": ""},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["title"] == ""

    def test_whitespace_only_required_field_rejected(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"given_name": "   "},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "given_name"]

    def test_invalid_region_code_rejected(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"region_code": "INVALID"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "region_code"]

    def test_invalid_email_rejected(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"email": "not-an-email"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "email"]

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        registration_service_update.side_effect = InvalidRegistrationStateError(
            "Cannot update registration after payment."
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "after payment" in response.json()["message"]

    def test_registration_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
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

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path("nonexistent", ULID()),
            data={"receipt_title": "Should Fail"},
        )
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

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Should Fail"},
        )
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

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUpdateRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-registration",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={
                "receipt_title": "Admin Updated",
                "given_name": "AdminEdit",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["receipt_title"] == "Admin Updated"
        assert data["given_name"] == "AdminEdit"
        assert data["user"]["uid"] == str(user.uid)

        registration_service_update.assert_called_once_with(
            registration,
            mode="admin",
            receipt_title="Admin Updated",
            given_name="AdminEdit",
        )

    def test_change_state(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"state": RegistrationState.CONFIRMED},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["state"] == RegistrationState.CONFIRMED

        registration_service_update.assert_called_once_with(
            registration,
            mode="admin",
            state=RegistrationState.CONFIRMED,
        )

    def test_change_state_from_cancelled(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"state": RegistrationState.PENDING},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["state"] == RegistrationState.PENDING

    def test_change_attendance_type(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        new_type = AttendanceType.objects.create(
            conference=conference,
            display_name="Poster Presentation",
            paper_required=True,
            admin_only=True,
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"attendance_type": str(new_type.uid)},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["attendance_type"]["uid"] == str(new_type.uid)

    def test_attendance_type_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        registration_service_update.side_effect = AttendanceType.DoesNotExist()
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"attendance_type": str(ULID())},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attendance_type"]
        assert "Invalid" in error["msg"]

    def test_handle_attendance_type_incompatible_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration_no_paper: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        registration_service_update.side_effect = AttendanceTypeIncompatibleError(
            "This attendance type requires a paper."
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration_no_paper.uid),
            data={"attendance_type": str(ULID())},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attendance_type"]
        assert "requires a paper" in error["msg"]

    def test_whitespace_only_required_field_rejected(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"given_name": "   "},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "given_name"]

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        registration_service_update.side_effect = InvalidRegistrationStateError(
            "Cannot update a cancelled registration."
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "cancelled registration" in response.json()["message"]

    def test_registration_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path("nonexistent", ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        registration: Registration,
        registration_service_update: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Global Admin Update"},
        )
        assert response.status_code == HTTPStatus.OK

        registration_service_update.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
        registration_service_update: MagicMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.patch(
            self.path(conference.name, registration.uid),
            data={"receipt_title": "Conference Admin Update"},
        )
        assert response.status_code == HTTPStatus.OK

        registration_service_update.assert_called_once()

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
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"receipt_title": "Should Fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

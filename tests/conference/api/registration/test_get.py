from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Paper,
    PaperState,
    Profile,
    Registration,
    RegistrationState,
    Track,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
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
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
    paper: Paper,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        attendance_type=attendance_type,
        paper=paper,
        given_name="John",
        family_name="Doe",
        email="john@example.com",
    )


@pytest.fixture
def registration_without_paper(
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        attendance_type=attendance_type,
    )


@pytest.mark.django_db
class TestGetMyRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-my-registration",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
        paper: Paper,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(registration.uid),
            "create_time": any_str,
            "conference": conference.name,
            "reference_code": registration.reference_code,
            "state": RegistrationState.PENDING,
            "paper": {
                "code": paper.code,
                "title": paper.title,
            },
            "attendance_type": {
                "uid": str(attendance_type.uid),
                "display_name": attendance_type.display_name,
                "admin_only": False,
                "paper_required": False,
            },
            "receipt_title": "",
            "title": "",
            "given_name": "John",
            "family_name": "Doe",
            "affiliation": "",
            "region_code": "",
            "email": "john@example.com",
            "phone": "",
            "self_introduction": "",
        }

    def test_registration_without_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration_without_paper: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(
            self.path(conference.name, registration_without_paper.uid)
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(registration_without_paper.uid)
        assert "paper" not in data

    def test_cannot_access_other_users_registration(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        other_registration = Registration.objects.create(
            conference=conference,
            user=other_user,
            attendance_type=attendance_type,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, other_registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_from_other_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        other_type = AttendanceType.objects.create(
            conference=other_conference,
            display_name="Other Type",
        )
        registration_in_other = Registration.objects.create(
            conference=other_conference,
            user=user,
            attendance_type=other_type,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, registration_in_other.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference", registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        registration: Registration,
    ) -> None:
        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestGetRegistration:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-registration",
            args=[conference_name, registration_uid],
        )

    @pytest.fixture
    def registrant_with_profile(self, faker: Faker) -> User:
        registrant = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(
            user=registrant,
            given_name="Alice",
            family_name="Smith",
            affiliation="University",
        )
        return registrant

    @pytest.fixture
    def admin_registration(
        self,
        conference: Conference,
        registrant_with_profile: User,
        attendance_type: AttendanceType,
    ) -> Registration:
        return Registration.objects.create(
            conference=conference,
            user=registrant_with_profile,
            attendance_type=attendance_type,
            given_name="Alice",
            family_name="Smith",
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
        registrant_with_profile: User,
        admin_registration: Registration,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, admin_registration.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(admin_registration.uid),
            "create_time": any_str,
            "conference": conference.name,
            "reference_code": admin_registration.reference_code,
            "state": RegistrationState.PENDING,
            "attendance_type": {
                "uid": str(attendance_type.uid),
                "display_name": attendance_type.display_name,
                "admin_only": False,
                "paper_required": False,
            },
            "receipt_title": "",
            "title": "",
            "given_name": "Alice",
            "family_name": "Smith",
            "affiliation": "",
            "region_code": "",
            "email": "",
            "phone": "",
            "self_introduction": "",
            "user": {
                "uid": str(registrant_with_profile.uid),
                "email": registrant_with_profile.email,
                "profile": {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "",
                },
            },
        }

    def test_user_without_profile(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        registrant = User.objects.create_user(username=faker.user_name())
        registration = Registration.objects.create(
            conference=conference,
            user=registrant,
            attendance_type=attendance_type,
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(registration.uid)
        assert "profile" not in data["user"]

    def test_registration_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_from_other_conference(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        other_type = AttendanceType.objects.create(
            conference=other_conference,
            display_name="Other Type",
        )
        registrant = User.objects.create_user(username=faker.user_name())
        registration_in_other = Registration.objects.create(
            conference=other_conference,
            user=registrant,
            attendance_type=other_type,
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, registration_in_other.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conference", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        registration: Registration,
    ) -> None:
        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_global_role_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
        non_admin_role: ConferenceRole,
    ) -> None:
        non_admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_admin,
            role=non_admin_role,
        )
        api_client.force_login(non_admin)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        registration: Registration,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=chair,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(chair)

        response = api_client.get(self.path(conference.name, registration.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

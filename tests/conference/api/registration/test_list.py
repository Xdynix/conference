from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

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


def create_registration(
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
    *,
    paper: Paper | None = None,
    state: RegistrationState = RegistrationState.PENDING,
    given_name: str = "",
    family_name: str = "",
    email: str = "",
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        attendance_type=attendance_type,
        paper=paper,
        state=state,
        given_name=given_name,
        family_name=family_name,
        email=email,
    )


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


@pytest.mark.django_db
class TestListMyRegistrations:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-my-registrations", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
        paper: Paper,
    ) -> None:
        registration = create_registration(
            conference,
            user,
            attendance_type,
            paper=paper,
            given_name="John",
            family_name="Doe",
            email="john@example.com",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
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
                },
            ],
        }

    def test_registration_without_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        registration = create_registration(conference, user, attendance_type)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(registration.uid)
        assert "paper" not in data

    def test_returns_only_registrations_for_current_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        user_registration = create_registration(conference, user, attendance_type)
        create_registration(conference, other_user, attendance_type)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(user_registration.uid)

    def test_scoped_to_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
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
        registration_in_conference = create_registration(
            conference,
            user,
            attendance_type,
        )
        create_registration(other_conference, user, other_type)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(registration_in_conference.uid)

    def test_returns_empty_list_when_no_registrations(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["items"] == []

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(self, api_client: Client, conference: Conference) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestListRegistrations:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-registrations", args=[conference_name])

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
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
        registration = create_registration(
            conference,
            registrant,
            attendance_type,
            given_name="Alice",
            family_name="Smith",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "uid": str(registration.uid),
                    "create_time": any_str,
                    "conference": conference.name,
                    "reference_code": registration.reference_code,
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
                        "uid": str(registrant.uid),
                        "email": registrant.email,
                        "profile": {
                            "given_name": "Alice",
                            "family_name": "Smith",
                            "affiliation": "University",
                            "region_code": "",
                        },
                    },
                },
            ]
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
        registration = create_registration(conference, registrant, attendance_type)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(registration.uid)
        assert "profile" not in data["user"]

    def test_returns_all_registrations(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        user_a = User.objects.create_user(username=faker.user_name())
        user_b = User.objects.create_user(username=faker.user_name())
        reg_a = create_registration(conference, user_a, attendance_type)
        reg_b = create_registration(conference, user_b, attendance_type)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        uids = {item["uid"] for item in response.json()["items"]}
        assert uids == {str(reg_a.uid), str(reg_b.uid)}

    def test_returns_empty_list_when_no_registrations(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["items"] == []

    def test_conference_not_found(self, api_client: Client, global_admin: User) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(self, api_client: Client, conference: Conference) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_global_role_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
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
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
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

    @pytest.mark.parametrize(
        ("search_term", "expected_given_name"),
        [
            ("REF-ABC123", "Alice"),  # reference_code
            ("PAPER-001", "Alice"),  # paper__code
            ("Alice", "Alice"),  # given_name
            ("Smith", "Alice"),  # family_name
            ("alice@example.com", "Alice"),  # email
        ],
    )
    def test_search_filter(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        attendance_type: AttendanceType,
        search_term: str,
        expected_given_name: str,
    ) -> None:
        registrant = User.objects.create_user(username=faker.user_name())
        paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=registrant,
            code="PAPER-001",
            title="Test Paper",
            state=PaperState.ACCEPTED,
        )
        target_registration = Registration.objects.create(
            conference=conference,
            user=registrant,
            attendance_type=attendance_type,
            paper=paper,
            reference_code="REF-ABC123",
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
        )
        other_user = User.objects.create_user(username=faker.user_name())
        Registration.objects.create(
            conference=conference,
            user=other_user,
            attendance_type=attendance_type,
            reference_code="REF-XYZ789",
            given_name="Bob",
            family_name="Jones",
            email="bob@example.com",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name), {"search": search_term})
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(target_registration.uid)
        assert data["given_name"] == expected_given_name

    def test_search_filter_case_insensitive(
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
            given_name="Alice",
            family_name="Smith",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name), {"search": "alice"})
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(registration.uid)

    def test_search_filter_partial_match(
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
            given_name="Alice",
            email="alice.smith@example.com",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name), {"search": "alice.smith"})
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(registration.uid)

    def test_search_filter_no_match(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        registrant = User.objects.create_user(username=faker.user_name())
        Registration.objects.create(
            conference=conference,
            user=registrant,
            attendance_type=attendance_type,
            given_name="Alice",
            family_name="Smith",
        )
        api_client.force_login(global_admin)

        response = api_client.get(
            self.path(conference.name),
            {"search": "nonexistent"},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["items"] == []

    def test_search_filter_empty_returns_all(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        user_a = User.objects.create_user(username=faker.user_name())
        user_b = User.objects.create_user(username=faker.user_name())
        reg_a = create_registration(conference, user_a, attendance_type)
        reg_b = create_registration(conference, user_b, attendance_type)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name), {"search": ""})
        assert response.status_code == HTTPStatus.OK

        uids = {item["uid"] for item in response.json()["items"]}
        assert uids == {str(reg_a.uid), str(reg_b.uid)}

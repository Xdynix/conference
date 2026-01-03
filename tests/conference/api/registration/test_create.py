from http import HTTPStatus
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceVisibility,
    Paper,
    PaperState,
    Registration,
    RegistrationState,
    RegistrationTitle,
    Track,
)
from app.core.models import User
from app.utils.enums import Region
from tests.helpers import any_str, approx_now, update_object


@pytest.fixture
def registrable_paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
        announce_time=timezone.now(),
    )


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
def admin_only_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Virtual (Admin Only)",
        admin_only=True,
        paper_required=True,
    )


def make_payload(
    attendance_type: AttendanceType,
    *,
    paper: str | None = None,
) -> dict[str, Any]:
    return {
        "paper": paper,
        "attendance_type": str(attendance_type.uid),
        "receipt_title": "University of Testing",
        "title": RegistrationTitle.DR,
        "given_name": "John",
        "family_name": "Doe",
        "affiliation": "Department of Computer Science",
        "region_code": Region.US.name,
        "email": "john.doe@example.com",
        "phone": "+1-555-123-4567",
        "self_introduction": "I am a researcher in the field of testing.",
    }


@pytest.mark.django_db
class TestCreateMyRegistration:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-my-registration", args=[conference_name])

    @pytest.fixture(autouse=True)
    def enable_registration(self, conference: Conference) -> None:
        update_object(conference, registration_enabled=True)

    def test_happy_path_with_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
        registrable_paper: Paper,
    ) -> None:
        payload = make_payload(paper_required_type, paper=registrable_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data == {
            "uid": any_str,
            "create_time": approx_now(),
            "conference": conference.name,
            "reference_code": any_str,
            "state": RegistrationState.PENDING,
            "paper": {
                "code": registrable_paper.code,
                "title": registrable_paper.title,
            },
            "attendance_type": {
                "uid": str(paper_required_type.uid),
                "display_name": paper_required_type.display_name,
                "admin_only": False,
                "paper_required": True,
            },
            "receipt_title": "University of Testing",
            "title": RegistrationTitle.DR,
            "given_name": "John",
            "family_name": "Doe",
            "affiliation": "Department of Computer Science",
            "region_code": Region.US.name,
            "email": "john.doe@example.com",
            "phone": "+1-555-123-4567",
            "self_introduction": "I am a researcher in the field of testing.",
        }

        registration = Registration.objects.get(uid=data["uid"])
        assert registration.user == user
        assert registration.conference == conference
        assert registration.paper == registrable_paper

    def test_happy_path_without_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type, paper=None)
        payload.pop("paper", None)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["state"] == RegistrationState.PENDING
        assert "paper" not in data
        assert data["attendance_type"]["paper_required"] is False

    def test_registration_not_enabled(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        update_object(conference, registration_enabled=False)
        payload = make_payload(no_paper_type)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert "not currently open" in response.json()["message"]

    def test_invalid_attendance_type(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type)
        payload["attendance_type"] = str(ULID())
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attendance_type"]
        assert "Invalid" in error["msg"]

    def test_admin_only_attendance_type_rejected(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        admin_only_type: AttendanceType,
    ) -> None:
        payload = make_payload(admin_only_type)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attendance_type"]

    def test_paper_required_but_not_provided(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
    ) -> None:
        payload = make_payload(paper_required_type, paper=None)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "paper"]
        assert "requires a paper" in error["msg"]

    def test_paper_provided_but_not_allowed(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
        registrable_paper: Paper,
    ) -> None:
        payload = make_payload(no_paper_type, paper=registrable_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "paper"]
        assert "does not allow" in error["msg"]

    def test_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
    ) -> None:
        payload = make_payload(paper_required_type, paper="NONEXISTENT-001")
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "paper"]
        assert "not found" in error["msg"]

    def test_paper_not_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
        registrable_paper: Paper,
    ) -> None:
        update_object(registrable_paper, announce_time=None)
        payload = make_payload(paper_required_type, paper=registrable_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "paper"]

    def test_paper_not_accepted(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
        registrable_paper: Paper,
    ) -> None:
        update_object(registrable_paper, state=PaperState.REJECTED)
        payload = make_payload(paper_required_type, paper=registrable_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "paper"]

    def test_paper_withdrawn(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
        registrable_paper: Paper,
    ) -> None:
        update_object(registrable_paper, withdraw_time=timezone.now())
        payload = make_payload(paper_required_type, paper=registrable_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type)
        api_client.force_login(user)

        response = api_client.post(self.path("nonexistent-conf"), data=payload)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        payload = make_payload(no_paper_type)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_empty_required_field_rejected(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type)
        payload["given_name"] = "   "
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "given_name"]

    def test_attendance_type_from_other_conference_rejected(
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
            admin_only=False,
        )
        payload = make_payload(other_type)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "attendance_type"]

    def test_paper_from_other_conference_rejected(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_required_type: AttendanceType,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name="Other Track",
        )
        other_paper = Paper.objects.create(
            conference=other_conference,
            track=other_track,
            owner=user,
            code="OTHER-001",
            title="Other Paper",
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        payload = make_payload(paper_required_type, paper=other_paper.code)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_title_optional(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        no_paper_type: AttendanceType,
    ) -> None:
        payload = make_payload(no_paper_type)
        payload["title"] = ""
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name), data=payload)
        assert response.status_code == HTTPStatus.CREATED

        assert response.json()["title"] == ""

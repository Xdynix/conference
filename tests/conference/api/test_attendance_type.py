from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
)
from app.conference.services import ConferenceService
from app.core.models import User
from tests.helpers import any_str


@pytest.fixture
def mock_visible_attendance_types(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(ConferenceService, "visible_attendance_types")


@pytest.mark.django_db
class TestListAttendanceTypes:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-attendance-types", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        mock_visible_attendance_types: AsyncMock,
    ) -> None:
        type_a = AttendanceType.objects.create(
            conference=conference,
            display_name="Oral Presentation",
            ordering=0,
            admin_only=False,
            paper_required=True,
        )
        type_b = AttendanceType.objects.create(
            conference=conference,
            display_name="Virtual Attendance",
            ordering=1,
            admin_only=True,
            paper_required=False,
        )
        mock_visible_attendance_types.return_value = AttendanceType.objects.filter(
            pk__in=[type_a.pk, type_b.pk]
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(type_a.uid),
                "display_name": "Oral Presentation",
                "admin_only": False,
                "paper_required": True,
            },
            {
                "uid": str(type_b.uid),
                "display_name": "Virtual Attendance",
                "admin_only": True,
                "paper_required": False,
            },
        ]

        mock_visible_attendance_types.assert_awaited_once_with(user, conference)

    def test_returns_empty_list_when_no_types(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        mock_visible_attendance_types: AsyncMock,
    ) -> None:
        mock_visible_attendance_types.return_value = AttendanceType.objects.none()
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_preserves_ordering(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        mock_visible_attendance_types: AsyncMock,
    ) -> None:
        type_c = AttendanceType.objects.create(
            conference=conference,
            display_name="Charlie",
            ordering=2,
            admin_only=False,
        )
        type_a = AttendanceType.objects.create(
            conference=conference,
            display_name="Alpha",
            ordering=0,
            admin_only=False,
        )
        type_b = AttendanceType.objects.create(
            conference=conference,
            display_name="Bravo",
            ordering=1,
            admin_only=False,
        )
        mock_visible_attendance_types.return_value = AttendanceType.objects.filter(
            pk__in=[type_a.pk, type_b.pk, type_c.pk]
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert [item["display_name"] for item in data] == ["Alpha", "Bravo", "Charlie"]

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("non-existent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestCreateAttendanceType:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-attendance-type", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "display_name": "Oral Presentation",
                "admin_only": False,
                "paper_required": True,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data == {
            "uid": any_str,
            "display_name": "Oral Presentation",
            "admin_only": False,
            "paper_required": True,
        }

        assert AttendanceType.objects.filter(uid=data["uid"]).exists()

    def test_uses_default_values(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Virtual Attendance"},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["admin_only"] is True
        assert data["paper_required"] is True

    def test_first_type_gets_ordering_zero(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "First Type"},
        )
        assert response.status_code == HTTPStatus.CREATED

        attendance_type = AttendanceType.objects.get(uid=response.json()["uid"])
        assert attendance_type.ordering == 0

    def test_appends_to_end_of_ordering(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        AttendanceType.objects.create(
            conference=conference,
            display_name="Existing Type",
            ordering=5,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "New Type"},
        )
        assert response.status_code == HTTPStatus.CREATED

        attendance_type = AttendanceType.objects.get(uid=response.json()["uid"])
        assert attendance_type.ordering == 6

    def test_trims_whitespace(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "  Oral Presentation  "},
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json()["display_name"] == "Oral Presentation"

    def test_duplicate_display_name_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        AttendanceType.objects.create(
            conference=conference,
            display_name="Oral Presentation",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Oral Presentation"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "already exists" in response.json()["message"]

    def test_same_display_name_different_conference_allowed(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        AttendanceType.objects.create(
            conference=other_conference,
            display_name="Oral Presentation",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Oral Presentation"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Chair Type"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Test Type"},
        )
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

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Test Type"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Test Type"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": "Test Type"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path("nonexistent-conf"),
            data={"display_name": "Test Type"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_empty_display_name_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"display_name": ""},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

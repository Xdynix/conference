from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import AttendanceType, Conference
from app.conference.services import ConferenceService
from app.core.models import User


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

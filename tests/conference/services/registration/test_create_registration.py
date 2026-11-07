import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from app.conference.models import (
    AttendanceType,
    Conference,
    Paper,
    Registration,
    RegistrationState,
    RegistrationTitle,
)
from app.conference.services import RegistrationService
from app.core.models import User


def create_registration(
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
    paper: Paper | None = None,
) -> Registration:
    return RegistrationService.create_registration(
        conference=conference,
        user=user,
        paper=paper,
        attendance_type=attendance_type,
        receipt_title="Test University",
        title=RegistrationTitle.DR,
        given_name="John",
        family_name="Doe",
        affiliation="Test University",
        region_code="US",
        email="john.doe@example.com",
        phone="+1-555-123-4567",
        self_introduction="Test introduction",
    )


@pytest.mark.django_db
class TestCreateRegistration:
    def test_happy_path(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
        paper: Paper,
    ) -> None:
        result = create_registration(conference, user, attendance_type, paper)

        db_result = Registration.objects.get(pk=result.pk)
        assert db_result.state == RegistrationState.PENDING
        assert db_result.paper == paper
        assert db_result.attendance_type == attendance_type
        assert db_result.title == RegistrationTitle.DR
        assert len(db_result.reference_code) == 8
        assert db_result.reference_code.isdigit()

    @pytest.mark.django_db(transaction=True)
    def test_retries_on_code_collision(
        self,
        mocker: MockerFixture,
        conference: Conference,
        user: User,
        attendance_type_no_paper: AttendanceType,
    ) -> None:
        mocker.patch(
            "app.conference.services.registration.generate_reference_code",
            side_effect=["11111111", "11111111", "22222222"],
        )

        first = create_registration(conference, user, attendance_type_no_paper)
        second = create_registration(conference, user, attendance_type_no_paper)

        assert first.reference_code == "11111111"
        assert second.reference_code == "22222222"
        assert Registration.objects.count() == 2

    @pytest.mark.django_db(transaction=True)
    def test_raises_non_code_collision_integrity_error(
        self,
        mocker: MockerFixture,
        conference: Conference,
        user: User,
        attendance_type_no_paper: AttendanceType,
    ) -> None:
        mocker.patch.object(
            Registration.objects,
            "create",
            side_effect=IntegrityError("Some other constraint violation"),
        )

        with pytest.raises(IntegrityError, match="Some other constraint violation"):
            create_registration(conference, user, attendance_type_no_paper)

    @pytest.mark.django_db(transaction=True)
    def test_exhausts_retries_on_persistent_collisions(
        self,
        mocker: MockerFixture,
        conference: Conference,
        user: User,
        attendance_type_no_paper: AttendanceType,
    ) -> None:
        mocker.patch.object(RegistrationService, "max_code_retries", 2)
        mocker.patch(
            "app.conference.services.registration.generate_reference_code",
            return_value="11111111",
        )
        create_registration(conference, user, attendance_type_no_paper)

        with pytest.raises(IntegrityError):
            create_registration(conference, user, attendance_type_no_paper)

        assert Registration.objects.count() == 1

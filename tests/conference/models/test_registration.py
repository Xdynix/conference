import secrets

import pytest
from django.db import IntegrityError
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    AttendanceType,
    Conference,
    Registration,
    RegistrationState,
)
from app.conference.models.registration import generate_reference_code
from app.core.models import User


@pytest.mark.django_db
class TestAttendanceType:
    def test_str(self, conference: Conference) -> None:
        attendance_type = AttendanceType(
            conference=conference,
            display_name="Oral Presentation",
        )
        assert str(attendance_type) == "Oral Presentation"

    def test_create_with_defaults(self, conference: Conference) -> None:
        attendance_type = AttendanceType.objects.create(
            conference=conference,
            display_name="Oral Presentation",
        )
        assert attendance_type.ordering == 0
        assert attendance_type.admin_only is True
        assert attendance_type.paper_required is True

    def test_unique_display_name_within_conference(
        self, conference: Conference
    ) -> None:
        AttendanceType.objects.create(
            conference=conference,
            display_name="Oral Presentation",
        )

        with pytest.raises(IntegrityError):
            AttendanceType.objects.create(
                conference=conference,
                display_name="Oral Presentation",
            )

    def test_same_display_name_different_conference(self, faker: Faker) -> None:
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        AttendanceType.objects.create(
            conference=conference1,
            display_name="Oral Presentation",
        )
        AttendanceType.objects.create(
            conference=conference2,
            display_name="Oral Presentation",
        )

    def test_ordering(self, conference: Conference) -> None:
        type_c = AttendanceType.objects.create(
            conference=conference,
            display_name="C Type",
            ordering=2,
        )
        type_a = AttendanceType.objects.create(
            conference=conference,
            display_name="A Type",
            ordering=0,
        )
        type_b = AttendanceType.objects.create(
            conference=conference,
            display_name="B Type",
            ordering=1,
        )

        types = list(AttendanceType.objects.filter(conference=conference))
        assert types == [type_a, type_b, type_c]

    def test_ordering_falls_back_to_display_name(self, conference: Conference) -> None:
        type_b = AttendanceType.objects.create(
            conference=conference,
            display_name="Bravo",
            ordering=0,
        )
        type_a = AttendanceType.objects.create(
            conference=conference,
            display_name="Alpha",
            ordering=0,
        )

        types = list(AttendanceType.objects.filter(conference=conference))
        assert types == [type_a, type_b]


class TestGenerateReferenceCode:
    def test_returns_8_digit_string(self) -> None:
        code = generate_reference_code()
        assert len(code) == 8
        assert code.isdigit()

    def test_pads_with_zeros(self, mocker: MockerFixture) -> None:
        mocker.patch.object(secrets, "randbelow", return_value=42)
        assert generate_reference_code() == "00000042"


@pytest.mark.django_db
class TestRegistration:
    @pytest.fixture
    def attendance_type(self, conference: Conference) -> AttendanceType:
        return AttendanceType.objects.create(
            conference=conference,
            display_name="Oral Presentation",
        )

    def test_str_with_name(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            given_name="John",
            family_name="Doe",
        )
        assert str(registration) == "John Doe"

    def test_str_with_given_name_only(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            given_name="John",
        )
        assert str(registration) == "John"

    def test_str_falls_back_to_reference_code(
        self, conference: Conference, user: User, attendance_type: AttendanceType
    ) -> None:
        registration = Registration(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            reference_code="12345678",
        )
        assert str(registration) == "12345678"

    def test_reference_code_auto_generated(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )
        assert len(registration.reference_code) == 8
        assert registration.reference_code.isdigit()

    def test_default_state_is_pending(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )
        assert registration.state == RegistrationState.PENDING

    def test_paper_is_optional(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )
        assert registration.paper is None

    def test_unique_reference_code_within_conference(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            reference_code="12345678",
        )

        with pytest.raises(IntegrityError):
            Registration.objects.create(
                conference=conference,
                user=user,
                attendance_type=attendance_type,
                reference_code="12345678",
            )

    def test_same_reference_code_different_conference(
        self,
        faker: Faker,
        user: User,
    ) -> None:
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        type1 = AttendanceType.objects.create(
            conference=conference1,
            display_name="General",
        )
        type2 = AttendanceType.objects.create(
            conference=conference2,
            display_name="General",
        )

        Registration.objects.create(
            conference=conference1,
            user=user,
            attendance_type=type1,
            reference_code="12345678",
        )
        Registration.objects.create(
            conference=conference2,
            user=user,
            attendance_type=type2,
            reference_code="12345678",
        )

    def test_multiple_registrations_per_user(
        self,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )
        Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )

        assert (
            Registration.objects.filter(user=user, conference=conference).count() == 2
        )

import pytest
from django.db import IntegrityError
from faker import Faker

from app.conference.models import AttendanceType, Conference


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

import pytest
from faker import Faker

from app.conference.models import (
    AttendanceType,
    Conference,
    Paper,
    PaperState,
    Registration,
    RegistrationState,
    Track,
)
from app.core.models import User


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
        paper_required=True,
        admin_only=False,
    )


@pytest.fixture
def attendance_type_no_paper(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="General Attendance",
        paper_required=False,
        admin_only=False,
    )


@pytest.fixture
def paper(user: User, conference: Conference, track: Track) -> Paper:
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
    user: User,
    conference: Conference,
    attendance_type: AttendanceType,
    paper: Paper,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=paper,
        attendance_type=attendance_type,
        state=RegistrationState.PENDING,
        receipt_title="Test University",
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation="Test University",
        region_code="US",
        email=faker.email(),
        phone=faker.phone_number(),
        self_introduction="Test introduction",
    )


@pytest.fixture
def registration_no_paper(
    faker: Faker,
    user: User,
    conference: Conference,
    attendance_type_no_paper: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=None,
        attendance_type=attendance_type_no_paper,
        state=RegistrationState.PENDING,
        receipt_title="Test Company",
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation="Test Company",
        region_code="US",
        email=faker.email(),
        phone=faker.phone_number(),
        self_introduction="Industry participant",
    )

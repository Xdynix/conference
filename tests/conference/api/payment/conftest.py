from decimal import Decimal

import pytest

from app.conference.models import (
    AttendanceType,
    Conference,
    Paper,
    PaperState,
    Payment,
    PaymentCurrency,
    PaymentMethod,
    PaymentType,
    Registration,
    RegistrationState,
    Track,
)
from app.core.models import User


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
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
        admin_only=False,
        paper_required=True,
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
        state=RegistrationState.CONFIRMED,
        given_name="John",
        family_name="Doe",
        email="john@example.com",
    )


@pytest.fixture
def payment(conference: Conference) -> Payment:
    return Payment.objects.create(
        conference=conference,
        amount=Decimal("150.00"),
        currency=PaymentCurrency.USD,
        type=PaymentType.PAYMENT,
        method=PaymentMethod.WIRE_TRANSFER,
        reference="TXN-001",
        note="Test payment",
    )

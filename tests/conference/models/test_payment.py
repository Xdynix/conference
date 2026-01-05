from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    AttendanceType,
    Conference,
    Payment,
    PaymentCurrency,
    PaymentItem,
    PaymentMethod,
    PaymentType,
    Registration,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPayment:
    @pytest.fixture
    def payment(self, conference: Conference) -> Payment:
        return Payment.objects.create(
            conference=conference,
            amount=Decimal("150.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
        )

    def test_str(self, conference: Conference) -> None:
        payment = Payment(
            conference=conference,
            amount=Decimal("150.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
        )
        assert str(payment) == f"[{conference}] Payment - 150.00 USD"

    def test_str_refund(self, conference: Conference) -> None:
        payment = Payment(
            conference=conference,
            amount=Decimal("50.00"),
            currency=PaymentCurrency.TWD,
            type=PaymentType.REFUND,
        )
        assert str(payment) == f"[{conference}] Refund - 50.00 TWD"

    def test_create_with_defaults(self, conference: Conference) -> None:
        payment = Payment.objects.create(
            conference=conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.OTHER,
        )
        assert payment.reference == ""
        assert payment.note == ""
        assert payment.delete_time is None

    def test_unique_reference_within_conference(self, conference: Conference) -> None:
        Payment.objects.create(
            conference=conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="TXN-001",
        )

        with pytest.raises(IntegrityError):
            Payment.objects.create(
                conference=conference,
                amount=Decimal("200.00"),
                currency=PaymentCurrency.USD,
                type=PaymentType.PAYMENT,
                method=PaymentMethod.WIRE_TRANSFER,
                reference="TXN-001",
            )

    def test_same_reference_different_conference(self, faker: Faker) -> None:
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        Payment.objects.create(
            conference=conference1,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="TXN-001",
        )
        Payment.objects.create(
            conference=conference2,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="TXN-001",
        )

    def test_empty_reference_not_unique(self, conference: Conference) -> None:
        Payment.objects.create(
            conference=conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="",
        )
        Payment.objects.create(
            conference=conference,
            amount=Decimal("200.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="",
        )

    def test_amount_non_negative_constraint(self, conference: Conference) -> None:
        with pytest.raises(IntegrityError):
            Payment.objects.create(
                conference=conference,
                amount=Decimal("-50.00"),
                currency=PaymentCurrency.USD,
                type=PaymentType.PAYMENT,
                method=PaymentMethod.OTHER,
            )

    def test_amount_zero_allowed(self, conference: Conference) -> None:
        payment = Payment.objects.create(
            conference=conference,
            amount=Decimal("0.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.OTHER,
        )
        assert payment.amount == Decimal("0.00")

    def test_active_excludes_soft_deleted(self, payment: Payment) -> None:
        update_object(payment, delete_time=timezone.now())

        assert Payment.objects.active().filter(pk=payment.pk).count() == 0

    def test_active_excludes_inactive_conference(
        self,
        conference: Conference,
        payment: Payment,
    ) -> None:
        update_object(conference, active=False)

        assert Payment.objects.active().filter(pk=payment.pk).count() == 0

    def test_active_includes_active_payments(self, payment: Payment) -> None:
        assert Payment.objects.active().filter(pk=payment.pk).count() == 1

    def test_formatted_amount_usd(self, conference: Conference) -> None:
        payment = Payment(
            conference=conference,
            amount=Decimal("1234.56"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
        )
        assert payment.formatted_amount == "1,234.56 USD"

    def test_formatted_amount_jpy(self, conference: Conference) -> None:
        payment = Payment(
            conference=conference,
            amount=Decimal(12345),
            currency=PaymentCurrency.JPY,
            type=PaymentType.PAYMENT,
        )
        assert payment.formatted_amount == "12,345 JPY"


@pytest.mark.django_db
class TestPaymentItem:
    @pytest.fixture
    def attendance_type(self, conference: Conference) -> AttendanceType:
        return AttendanceType.objects.create(
            conference=conference,
            display_name="General Attendance",
        )

    @pytest.fixture
    def registration(
        self,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> Registration:
        return Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
        )

    @pytest.fixture
    def payment(self, conference: Conference) -> Payment:
        return Payment.objects.create(
            conference=conference,
            amount=Decimal("150.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
        )

    def test_str(self, payment: Payment, registration: Registration) -> None:
        item = PaymentItem(
            payment=payment,
            registration=registration,
            amount=Decimal("100.00"),
        )
        assert str(item) == f"100.00 for {registration}"

    def test_create_with_defaults(
        self,
        payment: Payment,
        registration: Registration,
    ) -> None:
        item = PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("100.00"),
        )
        assert item.description == ""

    def test_amount_non_negative_constraint(
        self,
        payment: Payment,
        registration: Registration,
    ) -> None:
        with pytest.raises(IntegrityError):
            PaymentItem.objects.create(
                payment=payment,
                registration=registration,
                amount=Decimal("-50.00"),
            )

    def test_amount_zero_allowed(
        self,
        payment: Payment,
        registration: Registration,
    ) -> None:
        item = PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("0.00"),
        )
        assert item.amount == Decimal("0.00")

    def test_multiple_items_per_registration(
        self,
        payment: Payment,
        registration: Registration,
    ) -> None:
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("100.00"),
            description="Registration fee",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("50.00"),
            description="Extra page fee",
        )

        assert PaymentItem.objects.filter(registration=registration).count() == 2

    def test_multiple_items_per_payment(
        self,
        conference: Conference,
        payment: Payment,
        user: User,
    ) -> None:
        type1 = AttendanceType.objects.create(
            conference=conference,
            display_name="Type A",
        )
        type2 = AttendanceType.objects.create(
            conference=conference,
            display_name="Type B",
        )
        reg1 = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=type1,
        )
        reg2 = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=type2,
        )

        PaymentItem.objects.create(
            payment=payment,
            registration=reg1,
            amount=Decimal("100.00"),
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=reg2,
            amount=Decimal("50.00"),
        )

        assert payment.items.count() == 2

    def test_formatted_amount_uses_payment_currency(
        self,
        payment: Payment,
        registration: Registration,
    ) -> None:
        item = PaymentItem(
            payment=payment,
            registration=registration,
            amount=Decimal("100.00"),
        )
        assert item.formatted_amount == "100.00 USD"

    def test_formatted_amount_jpy(
        self,
        conference: Conference,
        registration: Registration,
    ) -> None:
        payment = Payment.objects.create(
            conference=conference,
            amount=Decimal(10000),
            currency=PaymentCurrency.JPY,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
        )
        item = PaymentItem(
            payment=payment,
            registration=registration,
            amount=Decimal(5000),
        )
        assert item.formatted_amount == "5,000 JPY"

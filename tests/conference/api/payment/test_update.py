from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Payment,
    PaymentCurrency,
    PaymentItem,
    PaymentMethod,
    PaymentType,
    Registration,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


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


@pytest.mark.django_db(transaction=True)
class TestUpdatePayment:
    @classmethod
    def path(cls, conference_name: str, payment_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-payment",
            args=[conference_name, payment_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "amount": "200.00",
                "currency": PaymentCurrency.EUR,
                "type": PaymentType.REFUND,
                "method": PaymentMethod.WIRE_TRANSFER,
                "reference": "TXN-002",
                "note": "Updated note",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(payment.uid)
        assert data["amount"] == "200.00"
        assert data["currency"] == PaymentCurrency.EUR
        assert data["type"] == PaymentType.REFUND
        assert data["method"] == PaymentMethod.WIRE_TRANSFER
        assert data["reference"] == "TXN-002"
        assert data["note"] == "Updated note"
        assert data["conference"] == conference.name
        assert data["create_time"] == any_str
        assert data["update_time"] == any_str

    def test_partial_update(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Partial update"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["note"] == "Partial update"
        assert data["amount"] == "150.00"
        assert data["reference"] == "TXN-001"

    def test_empty_payload_returns_existing(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        original_update_time = payment.update_time
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(payment.uid)
        assert data["amount"] == "150.00"

        payment.refresh_from_db()
        assert payment.update_time == original_update_time

    def test_update_with_items(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
        registration: Registration,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "items": [
                    {
                        "registration": str(registration.uid),
                        "amount": "100.00",
                        "description": "Registration fee",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["amount"] == "100.00"
        assert data["items"][0]["description"] == "Registration fee"
        assert data["items"][0]["registration"]["uid"] == str(registration.uid)

    def test_update_replaces_existing_items(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
        registration: Registration,
    ) -> None:
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("50.00"),
            description="Old item",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "items": [
                    {
                        "registration": str(registration.uid),
                        "amount": "75.00",
                        "description": "New item",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["amount"] == "75.00"
        assert data["items"][0]["description"] == "New item"

        assert PaymentItem.objects.filter(payment=payment).count() == 1

    def test_empty_items_clears_all(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
        registration: Registration,
    ) -> None:
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("50.00"),
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"items": []},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["items"] == []

        assert not payment.items.exists()

    def test_items_only_does_not_update_payment_fields(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
        registration: Registration,
    ) -> None:
        original_update_time = payment.update_time
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "items": [
                    {
                        "registration": str(registration.uid),
                        "amount": "100.00",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        payment.refresh_from_db()
        assert payment.update_time == original_update_time

    def test_reference_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        Payment.objects.create(
            conference=conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.OTHER,
            reference="EXISTING-REF",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"reference": "EXISTING-REF"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "reference" in response.json()["message"]

    def test_invalid_registration(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "items": [
                    {
                        "registration": str(ULID()),
                        "amount": "100.00",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "items", 0, "registration"]

    def test_registration_from_other_conference(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
        user: User,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        other_attendance = AttendanceType.objects.create(
            conference=other_conference,
            display_name="General",
        )
        other_registration = Registration.objects.create(
            conference=other_conference,
            user=user,
            attendance_type=other_attendance,
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={
                "items": [
                    {
                        "registration": str(other_registration.uid),
                        "amount": "100.00",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "items", 0, "registration"]

    def test_payment_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_soft_deleted_payment_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        update_object(payment, delete_time=timezone.now())
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path("nonexistent-conference", payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        payment: Payment,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_global_admin_authorized(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Admin update"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_global_read_all_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        payment: Payment,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        payment: Payment,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Conference admin update"},
        )
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
        payment: Payment,
        non_admin_role: ConferenceRole,
    ) -> None:
        member = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=member,
            role=non_admin_role,
        )
        api_client.force_login(member)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        payment: Payment,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=chair,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(chair)

        response = api_client.patch(
            self.path(conference.name, payment.uid),
            data={"note": "Should fail"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

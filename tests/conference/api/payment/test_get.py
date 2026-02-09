from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from ulid import ULID

from app.conference.models import (
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
    RegistrationState,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.mark.django_db
class TestGetPayment:
    @classmethod
    def path(cls, conference_name: str, payment_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-payment",
            args=[conference_name, payment_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        registration: Registration,
        payment: Payment,
    ) -> None:
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=Decimal("150.00"),
            description="Registration fee",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(payment.uid),
            "create_time": any_str,
            "update_time": any_str,
            "conference": conference.name,
            "amount": "150.00",
            "currency": PaymentCurrency.USD,
            "formatted_amount": "150.00 USD",
            "type": PaymentType.PAYMENT,
            "method": PaymentMethod.WIRE_TRANSFER,
            "reference": "TXN-001",
            "note": "Test payment",
            "items": [
                {
                    "amount": "150.00",
                    "formatted_amount": "150.00 USD",
                    "description": "Registration fee",
                    "registration": {
                        "uid": str(registration.uid),
                        "reference_code": registration.reference_code,
                        "state": RegistrationState.CONFIRMED,
                        "paper": registration.paper and registration.paper.code,
                        "attendance_type": registration.attendance_type.display_name,
                        "receipt_title": "",
                        "given_name": "John",
                        "family_name": "Doe",
                        "affiliation": "",
                        "region_code": "",
                        "email": "john@example.com",
                    },
                },
            ],
        }

    def test_payment_without_items(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(payment.uid)
        assert data["items"] == []

    def test_payment_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, ULID()))
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

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_payment_from_other_conference(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        payment_in_other = Payment.objects.create(
            conference=other_conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.OTHER,
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, payment_in_other.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conference", payment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        payment: Payment,
    ) -> None:
        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_global_role_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        payment: Payment,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.OK

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

        response = api_client.get(self.path(conference.name, payment.uid))
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
        non_admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=non_admin,
            role=non_admin_role,
        )
        api_client.force_login(non_admin)

        response = api_client.get(self.path(conference.name, payment.uid))
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

        response = api_client.get(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

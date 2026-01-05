from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

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
    RegistrationState,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


def create_payment(
    conference: Conference,
    *,
    amount: Decimal = Decimal("100.00"),
    currency: PaymentCurrency = PaymentCurrency.USD,
    payment_type: PaymentType = PaymentType.PAYMENT,
    method: PaymentMethod = PaymentMethod.WIRE_TRANSFER,
    reference: str = "",
    note: str = "",
) -> Payment:
    return Payment.objects.create(
        conference=conference,
        amount=amount,
        currency=currency,
        type=payment_type,
        method=method,
        reference=reference,
        note=note,
    )


@pytest.mark.django_db
class TestListPayments:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-payments", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        update_object(
            registration,
            state=RegistrationState.CONFIRMED,
            given_name="John",
            family_name="Doe",
            email="john@example.com",
        )
        payment = create_payment(
            conference,
            amount=Decimal("150.00"),
            currency=PaymentCurrency.USD,
            payment_type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="TXN-001",
            note="Test payment",
        )
        payment.items.create(
            registration=registration,
            amount=Decimal("150.00"),
            description="Registration fee",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "uid": str(payment.uid),
                    "create_time": any_str,
                    "update_time": any_str,
                    "conference": conference.name,
                    "amount": "150.00",
                    "currency": PaymentCurrency.USD,
                    "type": PaymentType.PAYMENT,
                    "method": PaymentMethod.WIRE_TRANSFER,
                    "reference": "TXN-001",
                    "note": "Test payment",
                    "items": [
                        {
                            "amount": "150.00",
                            "description": "Registration fee",
                            "registration": {
                                "uid": str(registration.uid),
                                "reference_code": registration.reference_code,
                                "state": RegistrationState.CONFIRMED,
                                "paper": registration.paper and registration.paper.code,
                                "attendance_type": (
                                    registration.attendance_type.display_name
                                ),
                                "receipt_title": "",
                                "given_name": "John",
                                "family_name": "Doe",
                                "affiliation": "",
                                "region_code": "",
                                "email": "john@example.com",
                            },
                        },
                    ],
                },
            ],
        }

    def test_payment_without_items(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        payment = create_payment(conference)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["uid"] == str(payment.uid)
        assert data["items"] == []

    def test_registration_without_paper(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        update_object(registration, paper=None)
        payment = create_payment(conference)
        payment.items.create(
            registration=registration,
            amount=Decimal("100.00"),
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        [item] = data["items"]
        assert "paper" not in item["registration"]

    def test_multiple_items_per_payment(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        reg1 = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            given_name="Alice",
        )
        reg2 = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            given_name="Bob",
        )
        payment = create_payment(conference, amount=Decimal("200.00"))
        PaymentItem.objects.create(
            payment=payment,
            registration=reg1,
            amount=Decimal("100.00"),
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=reg2,
            amount=Decimal("100.00"),
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert len(data["items"]) == 2
        given_names = {item["registration"]["given_name"] for item in data["items"]}
        assert given_names == {"Alice", "Bob"}

    def test_returns_all_payments(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        payment_a = create_payment(conference, reference="TXN-A")
        payment_b = create_payment(conference, reference="TXN-B")
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        uids = {item["uid"] for item in response.json()["items"]}
        assert uids == {str(payment_a.uid), str(payment_b.uid)}

    def test_excludes_soft_deleted_payments(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        active_payment = create_payment(conference, reference="TXN-ACTIVE")
        deleted_payment = create_payment(conference, reference="TXN-DELETED")
        update_object(deleted_payment, delete_time=timezone.now())
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        uids = {item["uid"] for item in response.json()["items"]}
        assert uids == {str(active_payment.uid)}

    def test_scoped_to_conference(
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
        payment_in_conference = create_payment(conference)
        create_payment(other_conference)
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        uids = {item["uid"] for item in response.json()["items"]}
        assert uids == {str(payment_in_conference.uid)}

    def test_returns_empty_list_when_no_payments(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["items"] == []

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_global_role_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_authorized(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
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
        non_admin_role: ConferenceRole,
    ) -> None:
        member = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=member,
            role=non_admin_role,
        )
        api_client.force_login(member)

        response = api_client.get(self.path(conference.name))
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
        chair = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=chair,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

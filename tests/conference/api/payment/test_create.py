from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
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
    PaymentMethod,
    PaymentType,
    Registration,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.mark.django_db(transaction=True)
class TestCreatePayment:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-payment", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "150.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.WIRE_TRANSFER,
                "reference": "TXN-001",
                "note": "Test payment",
                "items": [
                    {
                        "registration": str(registration.uid),
                        "amount": "150.00",
                        "description": "Registration fee",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["uid"] == any_str
        assert data["amount"] == "150.00"
        assert data["currency"] == PaymentCurrency.USD
        assert data["type"] == PaymentType.PAYMENT
        assert data["method"] == PaymentMethod.WIRE_TRANSFER
        assert data["reference"] == "TXN-001"
        assert data["note"] == "Test payment"
        assert data["conference"] == conference.name
        assert data["create_time"] == any_str
        assert data["update_time"] == any_str
        assert len(data["items"]) == 1
        assert data["items"][0]["amount"] == "150.00"
        assert data["items"][0]["description"] == "Registration fee"
        assert data["items"][0]["registration"]["uid"] == str(registration.uid)

    def test_minimal_payload(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.EUR,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["amount"] == "100.00"
        assert data["reference"] == ""
        assert data["note"] == ""
        assert data["items"] == []

    def test_create_with_multiple_items(
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
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "200.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.WIRE_TRANSFER,
                "items": [
                    {"registration": str(reg1.uid), "amount": "100.00"},
                    {"registration": str(reg2.uid), "amount": "100.00"},
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert len(data["items"]) == 2
        given_names = {item["registration"]["given_name"] for item in data["items"]}
        assert given_names == {"Alice", "Bob"}

    def test_reference_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
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

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "50.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
                "reference": "EXISTING-REF",
            },
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "reference" in response.json()["message"]

    def test_empty_reference_no_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        Payment.objects.create(
            conference=conference,
            amount=Decimal("100.00"),
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.OTHER,
            reference="",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "50.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
                "reference": "",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_invalid_registration(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
                "items": [
                    {"registration": str(ULID()), "amount": "100.00"},
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

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
                "items": [
                    {"registration": str(other_registration.uid), "amount": "100.00"},
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "items", 0, "registration"]

    def test_invalid_second_registration(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "200.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
                "items": [
                    {"registration": str(registration.uid), "amount": "100.00"},
                    {"registration": str(ULID()), "amount": "100.00"},
                ],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "items", 1, "registration"]

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path("nonexistent-conference"),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_global_admin_authorized(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_global_read_all_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

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

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.CREATED

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

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
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

        response = api_client.post(
            self.path(conference.name),
            data={
                "amount": "100.00",
                "currency": PaymentCurrency.USD,
                "type": PaymentType.PAYMENT,
                "method": PaymentMethod.CREDIT_CARD,
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

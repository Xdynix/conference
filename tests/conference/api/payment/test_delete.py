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
    Payment,
    PaymentCurrency,
    PaymentMethod,
    PaymentType,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


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


@pytest.mark.django_db
class TestDeletePayment:
    @classmethod
    def path(cls, conference_name: str, payment_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:delete-payment",
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

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

        payment.refresh_from_db()
        assert payment.delete_time is not None

    def test_payment_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_already_deleted_payment_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        update_object(payment, delete_time=timezone.now())
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path("nonexistent-conference", payment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        payment: Payment,
    ) -> None:
        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_global_admin_authorized(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        payment: Payment,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

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

        response = api_client.delete(self.path(conference.name, payment.uid))
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

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

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

        response = api_client.delete(self.path(conference.name, payment.uid))
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

        response = api_client.delete(self.path(conference.name, payment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

from http import HTTPStatus
from textwrap import dedent

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    Paper,
    PaperState,
    Payment,
    PaymentCurrency,
    PaymentItem,
    PaymentMethod,
    PaymentType,
    Receipt,
    Registration,
    RegistrationState,
    Track,
)
from app.core.models import User
from tests.helpers import any_str, update_object


@pytest.fixture(autouse=True)
def enable_registration(conference: Conference) -> None:
    update_object(conference, registration_enabled=True)


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="General Attendee",
        admin_only=False,
        paper_required=False,
    )


@pytest.fixture
def attendance_type_with_paper(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
        admin_only=False,
        paper_required=True,
    )


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="A Novel Approach to Machine Learning",
        state=PaperState.ACCEPTED,
        announce_time=timezone.now(),
    )


@pytest.mark.django_db
class TestRegistrationE2E:
    @classmethod
    def create_my_registration_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-my-registration", args=[conference_name])

    @classmethod
    def get_my_registration_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:get-my-registration",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def update_my_registration_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:update-my-registration",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def cancel_my_registration_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:cancel-my-registration",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def get_registration_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:get-registration",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def update_registration_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:update-registration",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def generate_receipt_path(
        cls,
        conference_name: str,
        registration_uid: ULID,
    ) -> str:
        return reverse(
            "api-1.0.0:generate-receipt",
            args=[conference_name, registration_uid],
        )

    @classmethod
    def get_receipt_path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-receipt", args=[uid])

    def test_user_registration_flow(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type: AttendanceType,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.create_my_registration_path(conference.name),
            data={
                "attendance_type": str(attendance_type.uid),
                "receipt_title": "University of Testing",
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "Test University",
                "region_code": "US",
                "email": "alice@example.com",
                "phone": "+1234567890",
                "self_introduction": "I am a researcher in machine learning.",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["state"] == RegistrationState.PENDING
        assert data["given_name"] == "Alice"
        assert data["family_name"] == "Smith"
        assert data["receipt_title"] == "University of Testing"
        assert data["reference_code"] == any_str

        registration_uid = ULID.from_str(data["uid"])

        response = api_client.get(
            self.get_my_registration_path(conference.name, registration_uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["uid"] == str(registration_uid)
        assert response.json()["given_name"] == "Alice"

        response = api_client.patch(
            self.update_my_registration_path(conference.name, registration_uid),
            data={
                "given_name": "Alicia",
                "affiliation": "Updated University",
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["given_name"] == "Alicia"
        assert response.json()["affiliation"] == "Updated University"
        assert response.json()["family_name"] == "Smith"

        response = api_client.get(
            self.get_my_registration_path(conference.name, registration_uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["given_name"] == "Alicia"

        response = api_client.post(
            self.cancel_my_registration_path(conference.name, registration_uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == RegistrationState.CANCELLED

        registration = Registration.objects.get(uid=registration_uid)
        assert registration.state == RegistrationState.CANCELLED

    def test_registration_with_paper_flow(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        attendance_type_with_paper: AttendanceType,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.create_my_registration_path(conference.name),
            data={
                "paper": paper.code,
                "attendance_type": str(attendance_type_with_paper.uid),
                "receipt_title": "Research Institute",
                "given_name": "Bob",
                "family_name": "Johnson",
                "affiliation": "Research Institute",
                "region_code": "GB",
                "email": "bob@research.org",
                "phone": "+441234567890",
                "self_introduction": "Presenting our accepted paper.",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["state"] == RegistrationState.PENDING
        assert data["paper"]["code"] == paper.code
        assert data["paper"]["title"] == paper.title
        assert data["attendance_type"]["display_name"] == "Oral Presentation"

    def test_admin_receipt_flow(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            given_name="Charlie",
            family_name="Brown",
            email="charlie@example.com",
            receipt_title="Charlie's Company",
            affiliation="Tech Corp",
            region_code="US",
            phone="+1987654321",
            self_introduction="Attending the conference.",
        )

        payment = Payment.objects.create(
            conference=conference,
            amount=750,
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="PAY-12345",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=500,
            description="Conference Fee",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=250,
            description="Workshop Fee",
        )

        api_client.force_login(conference_chair)

        response = api_client.get(
            self.get_registration_path(conference.name, registration.uid),
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["uid"] == str(registration.uid)
        assert data["given_name"] == "Charlie"
        assert data["user"]["uid"] == str(user.uid)
        assert "receipt_url" not in data

        template = dedent(
            """<html>
            <body>
            <h1>Official Receipt</h1>
            <p>Conference: {{ registration.conference.display_name }}</p>
            <p>Receipt Title: {{ registration.receipt_title }}</p>
            <p>
                Registrant:
                {{ registration.given_name }} {{ registration.family_name }}
            </p>
            <h2>Payment Items</h2>
            <ul>
            {% for item in registration.payment_items.all() -%}
            <li>{{ item.description }}: {{ item.formatted_amount }}</li>
            {% endfor -%}
            </ul>
            </body>
            </html>"""
        )

        response = api_client.post(
            self.generate_receipt_path(conference.name, registration.uid),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["uid"] == str(registration.uid)
        receipt_url = data["receipt_url"]

        assert Receipt.objects.filter(registration=registration).exists()
        receipt = Receipt.objects.get(registration=registration)
        assert "Charlie Brown" in receipt.rendered_html
        assert "Conference Fee: 500.00 USD" in receipt.rendered_html
        assert "Workshop Fee: 250.00 USD" in receipt.rendered_html

        response = api_client.get(
            self.get_registration_path(conference.name, registration.uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["receipt_url"] == receipt_url

        api_client.logout()

        response = api_client.get(receipt_url)
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/html"
        assert b"Charlie Brown" in response.content
        assert b"Conference Fee: 500.00 USD" in response.content

        api_client.force_login(conference_chair)

        updated_template = dedent(
            """<html>
            <body>
            <h1>Updated Receipt</h1>
            <p>Reference: {{ registration.reference_code }}</p>
            </body>
            </html>"""
        )

        response = api_client.post(
            self.generate_receipt_path(conference.name, registration.uid),
            data={"template": updated_template},
        )
        assert response.status_code == HTTPStatus.OK

        assert Receipt.objects.filter(registration=registration).count() == 1

        api_client.logout()

        response = api_client.get(receipt_url)
        assert response.status_code == HTTPStatus.OK
        assert b"Updated Receipt" in response.content
        assert registration.reference_code.encode() in response.content

    def test_admin_registration_state_management(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        registration = Registration.objects.create(
            conference=conference,
            user=user,
            attendance_type=attendance_type,
            state=RegistrationState.PENDING,
            given_name="Diana",
            family_name="Prince",
            email="diana@example.com",
            receipt_title="Wonder Corp",
            affiliation="Wonder Corp",
            region_code="US",
            phone="+1555555555",
            self_introduction="Looking forward to the conference.",
        )

        api_client.force_login(conference_chair)

        response = api_client.get(
            self.get_registration_path(conference.name, registration.uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == RegistrationState.PENDING

        response = api_client.patch(
            self.update_registration_path(conference.name, registration.uid),
            data={"state": RegistrationState.CONFIRMED},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == RegistrationState.CONFIRMED

        registration.refresh_from_db()
        assert registration.state == RegistrationState.CONFIRMED

        response = api_client.patch(
            self.update_registration_path(conference.name, registration.uid),
            data={
                "given_name": "Diana Updated",
                "receipt_title": "Updated Wonder Corp",
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["given_name"] == "Diana Updated"
        assert response.json()["receipt_title"] == "Updated Wonder Corp"
        assert response.json()["state"] == RegistrationState.CONFIRMED

    def test_full_registration_lifecycle_with_receipt(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        user: User,
        attendance_type: AttendanceType,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.create_my_registration_path(conference.name),
            data={
                "attendance_type": str(attendance_type.uid),
                "receipt_title": "Full Lifecycle Corp",
                "given_name": "Eve",
                "family_name": "Wilson",
                "affiliation": "Lifecycle Inc",
                "region_code": "CA",
                "email": "eve@lifecycle.com",
                "phone": "+1999888777",
                "self_introduction": "Testing the full lifecycle.",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        registration_uid = ULID.from_str(data["uid"])
        assert data["state"] == RegistrationState.PENDING

        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.update_registration_path(conference.name, registration_uid),
            data={"state": RegistrationState.CONFIRMED},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == RegistrationState.CONFIRMED

        registration = Registration.objects.get(uid=registration_uid)
        payment = Payment.objects.create(
            conference=conference,
            amount=100,
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.CREDIT_CARD,
            reference="CC-99999",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=100,
            description="Registration Fee",
        )

        template = "<p>Receipt for {{ registration.given_name }} - Total: 100 USD</p>"
        response = api_client.post(
            self.generate_receipt_path(conference.name, registration_uid),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK
        receipt_url = response.json()["receipt_url"]

        api_client.logout()

        response = api_client.get(receipt_url)
        assert response.status_code == HTTPStatus.OK
        assert b"Receipt for Eve" in response.content

        api_client.force_login(user)

        response = api_client.get(
            self.get_my_registration_path(conference.name, registration_uid),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == RegistrationState.CONFIRMED

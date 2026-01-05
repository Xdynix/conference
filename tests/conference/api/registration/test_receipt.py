from http import HTTPStatus
from textwrap import dedent

import pytest
from django.test import Client
from django.urls import reverse
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
from tests.helpers import update_object


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
    return AttendanceType.objects.create(
        conference=conference,
        display_name="Oral Presentation",
        admin_only=False,
        paper_required=False,
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
    )


@pytest.fixture
def registration(
    conference: Conference,
    user: User,
    paper: Paper,
    attendance_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=paper,
        attendance_type=attendance_type,
        given_name="Alice",
        family_name="Smith",
        email="alice@example.com",
        receipt_title="University of Testing",
    )


@pytest.mark.django_db
class TestGenerateReceipt:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:generate-receipt",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        paper: Paper,
    ) -> None:
        payment = Payment.objects.create(
            conference=conference,
            amount=500,
            currency=PaymentCurrency.USD,
            type=PaymentType.PAYMENT,
            method=PaymentMethod.WIRE_TRANSFER,
            reference="TXN-12345",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=300,
            description="Registration Fee",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=200,
            description="Banquet",
        )

        template = dedent(
            """<html>
            <body>
            <h1>Receipt</h1>
            <p>Conference: {{ registration.conference.display_name }}</p>
            <p>Receipt Title: {{ registration.receipt_title }}</p>
            <p>
                Registrant:
                {{ registration.given_name }} {{ registration.family_name }}
            </p>
            <p>Attendance Type: {{ registration.attendance_type.display_name }}</p>
            <h2>Paper</h2>
            <p>Code: {{ registration.paper.code }}</p>
            <p>Title: {{ registration.paper.title }}</p>
            <p>Track: {{ registration.paper.track.display_name }}</p>
            <h2>Payment Items</h2>
            <ul>
            {% for item in registration.payment_items.all() -%}
            <li>{{ item.description }}: {{ item.formatted_amount }}</li>
            {% endfor -%}
            </ul>
            </body>
            </html>"""
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(registration.uid)

        receipt = Receipt.objects.get(registration=registration)
        expected_html = dedent(
            f"""<html>
            <body>
            <h1>Receipt</h1>
            <p>Conference: {conference.display_name}</p>
            <p>Receipt Title: University of Testing</p>
            <p>
                Registrant:
                Alice Smith
            </p>
            <p>Attendance Type: {registration.attendance_type.display_name}</p>
            <h2>Paper</h2>
            <p>Code: PAPER-001</p>
            <p>Title: A Novel Approach to Machine Learning</p>
            <p>Track: {paper.track.display_name}</p>
            <h2>Payment Items</h2>
            <ul>
            <li>Registration Fee: 300.00 USD</li>
            <li>Banquet: 200.00 USD</li>
            </ul>
            </body>
            </html>"""
        )
        assert receipt.rendered_html == expected_html

    def test_regenerating_replaces_existing_receipt(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        Receipt.objects.create(registration=registration, rendered_html="<p>Old</p>")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "<p>{{ registration.reference_code }}</p>"},
        )
        assert response.status_code == HTTPStatus.OK

        assert Receipt.objects.filter(registration=registration).count() == 1
        receipt = Receipt.objects.get(registration=registration)
        assert receipt.rendered_html == f"<p>{registration.reference_code}</p>"

    def test_escapes_html_in_template_variables(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        update_object(registration, receipt_title="<script>alert('xss')</script>")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "<p>{{ registration.receipt_title }}</p>"},
        )
        assert response.status_code == HTTPStatus.OK

        receipt = Receipt.objects.get(registration=registration)
        assert (
            receipt.rendered_html
            == "<p>&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;</p>"
        )

    def test_template_syntax_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ unclosed"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "unexpected" in response.json()["message"].lower()

    def test_undefined_variable_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ undefined_var }}"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined_var" in error["msg"]

    def test_rejects_cancelled_registration(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ registration.reference_code }}"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "cancelled" in response.json()["message"].lower()

    @pytest.mark.parametrize(
        "state",
        [RegistrationState.PENDING, RegistrationState.CONFIRMED],
    )
    def test_allows_pending_and_confirmed_registrations(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        state: RegistrationState,
    ) -> None:
        update_object(registration, state=state)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ registration.reference_code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_validates_template_required(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_validates_template_not_empty(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": ""},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_registration_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, ULID()),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        registration: Registration,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        registration: Registration,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ registration.reference_code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ registration.reference_code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "{{ registration.reference_code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestGetReceipt:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-receipt", args=[uid])

    def test_happy_path(
        self,
        client: Client,
        registration: Registration,
    ) -> None:
        Receipt.objects.create(
            registration=registration,
            rendered_html="<html><body><h1>Receipt</h1></body></html>",
        )

        response = client.get(self.path(registration.uid))

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/html"
        assert response.content == b"<html><body><h1>Receipt</h1></body></html>"

    def test_returns_full_rendered_content(
        self,
        client: Client,
        registration: Registration,
    ) -> None:
        html_content = dedent(
            """<!DOCTYPE html>
            <html>
            <head><title>Receipt</title></head>
            <body>
            <h1>Official Receipt</h1>
            <p>Amount: $500.00</p>
            <img src="data:image/png;base64,iVBORw0KGgo=" alt="Stamp">
            </body>
            </html>
            """
        )
        Receipt.objects.create(registration=registration, rendered_html=html_content)

        response = client.get(self.path(registration.uid))

        assert response.status_code == HTTPStatus.OK
        assert response.content.decode() == html_content

    def test_receipt_not_found(
        self,
        client: Client,
        registration: Registration,
    ) -> None:
        response = client.get(self.path(registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_not_found(self, client: Client) -> None:
        response = client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

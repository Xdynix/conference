from collections.abc import Coroutine
from http import HTTPStatus
from pathlib import Path
from typing import Any, NoReturn
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    Paper,
    PaperAuthor,
    PaperState,
    Payment,
    PaymentItem,
    Profile,
    Receipt,
    Registration,
    RegistrationState,
    RegistrationTitle,
    Track,
)
from app.core.models import User
from app.utils.enums import Region
from app.utils.typst import CompilationError
from tests.helpers import update_object

FAKE_PDF = b"%PDF-fake-receipt"
TEMPLATE = "#set page(width: auto)\nReceipt template"


@pytest.fixture
def attendance_type(conference: Conference) -> AttendanceType:
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
        title="Test Paper",
        state=PaperState.ACCEPTED,
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
        paper=paper,
        attendance_type=attendance_type,
        state=RegistrationState.CONFIRMED,
        title=RegistrationTitle.DR,
        given_name="John",
        family_name="Doe",
        affiliation="University of Testing",
        region_code="US",
        email="john@example.com",
        phone="+1234567890",
        receipt_title="University of Testing",
    )


@pytest.fixture
def registration_no_paper(
    conference: Conference,
    user: User,
    attendance_type: AttendanceType,
) -> Registration:
    return Registration.objects.create(
        conference=conference,
        user=user,
        paper=None,
        attendance_type=attendance_type,
        state=RegistrationState.CONFIRMED,
        given_name="Jane",
        family_name="Doe",
        email="jane@example.com",
    )


@pytest.fixture
def compile_template(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "app.conference.api.registration.receipt.compile_template",
        return_value=FAKE_PDF,
    )


@pytest.fixture(autouse=True)
def file_download_mode(settings: LazySettings) -> None:
    settings.FILE_DOWNLOAD_MODE = "django"


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
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(registration.uid)

        compile_template.assert_called_once()
        call_args = compile_template.call_args
        assert call_args[0][0] == TEMPLATE

        receipt = Receipt.objects.get(registration=registration)
        assert receipt.template == TEMPLATE
        assert receipt.rendered_pdf.name

    def test_context_structure(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        Profile.objects.create(
            user=registration.user,
            given_name="Profile John",
            family_name="Profile Doe",
            affiliation="Profile University",
            region_code="US",
        )
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Bob",
            family_name="Author",
            affiliation="Stanford",
            region_code="US",
            email="bob@example.com",
            corresponding=True,
            ordering=1,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]

        assert context["conference"]["name"] == conference.name
        assert context["conference"]["display_name"] == conference.display_name

        reg = context["registration"]
        assert reg["uid"] == str(registration.uid)
        assert reg["create_date"] == {
            "year": registration.create_time.year,
            "month": registration.create_time.month,
            "day": registration.create_time.day,
        }
        assert reg["reference_code"] == registration.reference_code
        assert reg["given_name"] == "John"
        assert reg["family_name"] == "Doe"
        assert reg["region_name"] == Region.get_label("US")
        assert reg["receipt_title"] == "University of Testing"
        assert reg["attendance_type"]["display_name"] == "Oral Presentation"

        assert reg["user"]["given_name"] == "Profile John"
        assert reg["user"]["family_name"] == "Profile Doe"

        assert reg["paper"] is not None
        assert reg["paper"]["code"] == "PAPER-001"
        assert len(reg["paper"]["authors"]) == 1
        assert reg["paper"]["authors"][0]["given_name"] == "Bob"

        assert context["extra"] == {}

    def test_extra_context(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)
        extra = {"invoice_number": "INV-2026-001", "note": "Paid in full"}

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE, "extra_context": extra},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["extra"] == extra

        receipt = Receipt.objects.get(registration=registration)
        assert receipt.context["extra"] == extra

    def test_context_without_paper(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration_no_paper: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration_no_paper.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["registration"]["paper"] is None

    def test_context_payment_items(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        payment = Payment.objects.create(
            conference=conference,
            amount=500_00,
            currency="USD",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=300_00,
            description="Registration Fee",
        )
        PaymentItem.objects.create(
            payment=payment,
            registration=registration,
            amount=200_00,
            description="Extra Page Fee",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        items = context["registration"]["payment_items"]
        assert len(items) == 2
        assert items[0]["description"] == "Registration Fee"
        assert items[1]["description"] == "Extra Page Fee"

    def test_regeneration_replaces_existing(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "first template"},
        )
        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "second template"},
        )
        assert response.status_code == HTTPStatus.OK
        assert Receipt.objects.filter(registration=registration).count() == 1

        receipt = Receipt.objects.get(registration=registration)
        assert receipt.template == "second template"

        compile_template.assert_called()

    @pytest.mark.django_db(transaction=True)
    def test_regeneration_deletes_old_file(
        self,
        api_client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "first template"},
        )
        old_receipt = Receipt.objects.get(registration=registration)
        old_file = media_root / old_receipt.rendered_pdf.name
        assert old_file.exists()

        compile_template.return_value = b"%PDF-second"
        api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": "second template"},
        )

        new_receipt = Receipt.objects.get(registration=registration)
        new_file = media_root / new_receipt.rendered_pdf.name
        assert new_file.exists()
        assert not old_file.exists()

    def test_cancelled_registration_rejected(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "cancelled" in response.json()["message"].lower()
        compile_template.assert_not_called()

    def test_pending_registration_allowed(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        update_object(registration, state=RegistrationState.PENDING)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_compilation_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        compile_template.side_effect = CompilationError(
            "undefined variable",
            diagnostic="error at line 1",
            hints=[],
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined variable" in error["msg"]

    def test_compilation_timeout(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch(
            "app.conference.api.registration.receipt.compile_template",
            return_value=FAKE_PDF,
        )

        async def raise_timeout(
            coro: Coroutine[Any, Any, Any],
            *_: Any,
            **__: Any,
        ) -> NoReturn:
            coro.close()
            raise TimeoutError

        mocker.patch(
            "app.conference.api.registration.receipt.asyncio.wait_for",
            side_effect=raise_timeout,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "timed out" in error["msg"].lower()

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

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", registration.uid),
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_registration_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, ULID()),
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

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
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestGetReceipt:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-receipt", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        registration: Registration,
    ) -> None:
        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)

        response = api_client.get(self.path(registration.uid))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert b"".join(response.streaming_content) == FAKE_PDF  # type: ignore[attr-defined]

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_receipt_not_generated(
        self, api_client: Client, registration: Registration
    ) -> None:
        response = api_client.get(self.path(registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        media_root: Path,
        registration: Registration,
    ) -> None:
        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)
        file_path = media_root / receipt.rendered_pdf.name
        file_path.unlink()

        response = api_client.get(self.path(registration.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestGetReceiptDecorated:
    @classmethod
    def path(cls, uid: ULID, filename: str) -> str:
        return reverse("api-1.0.0:get-receipt-ex", args=[uid, filename])

    def test_happy_path(
        self,
        api_client: Client,
        registration: Registration,
    ) -> None:
        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)

        response = api_client.get(self.path(registration.uid, "receipt.pdf"))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert b"".join(response.streaming_content) == FAKE_PDF  # type: ignore[attr-defined]

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID(), "receipt.pdf"))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestPreviewReceipt:
    @classmethod
    def path(cls, conference_name: str, registration_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:preview-receipt",
            args=[conference_name, registration_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert response.content == FAKE_PDF

        compile_template.assert_called_once()

    def test_no_save(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK
        assert not Receipt.objects.exists()

        compile_template.assert_called_once()

    def test_compilation_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        compile_template.side_effect = CompilationError(
            "undefined variable",
            diagnostic="error at line 1",
            hints=[],
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined variable" in error["msg"]

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        registration: Registration,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        registration: Registration,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, registration.uid),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestListReceipts:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-receipts", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={"extra": {"invoice_number": "INV-001"}},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()
        assert data["registration_uid"] == str(registration.uid)
        assert data["registration_reference_code"] == registration.reference_code
        assert data["extra"] == {"invoice_number": "INV-001"}
        assert data["create_time"] is not None
        assert data["update_time"] is not None

    def test_empty_list(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_extra_defaults_to_empty_dict(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()[0]["extra"] == {}

    def test_excludes_other_conferences(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        registration: Registration,
    ) -> None:
        other_conference = Conference.objects.create(
            name="other-conf",
            display_name="Other Conference",
        )
        other_attendance = AttendanceType.objects.create(
            conference=other_conference,
            display_name="Other Attendance",
            admin_only=False,
        )
        other_registration = Registration.objects.create(
            conference=other_conference,
            user=registration.user,
            attendance_type=other_attendance,
            state=RegistrationState.CONFIRMED,
            given_name="Jane",
            family_name="Doe",
            email="jane@example.com",
        )
        other_receipt = Receipt.objects.create(
            registration=other_registration,
            template=TEMPLATE,
            context={},
        )
        other_receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)

        receipt = Receipt.objects.create(
            registration=registration,
            template=TEMPLATE,
            context={},
        )
        receipt.rendered_pdf.save("receipt.pdf", ContentFile(FAKE_PDF), save=True)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()
        assert data["registration_uid"] == str(registration.uid)

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

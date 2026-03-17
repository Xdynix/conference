from http import HTTPStatus
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from app.conference.models import Conference, ConferenceFile
from app.core.models import User
from app.infra.models import Mutex
from app.utils.files import FileTooLargeError, InvalidFileTypeError
from tests.helpers import approx_now, update_object

FAKE_PDF = b"%PDF-1.4 fake content"


@pytest.fixture(autouse=True)
def file_download_mode(settings: LazySettings) -> None:
    settings.FILE_DOWNLOAD_MODE = "django"


@pytest.fixture
def conference_file(conference: Conference) -> ConferenceFile:
    cf = ConferenceFile.objects.create(
        conference=conference,
        name="payment-form",
        filename="Payment Form.pdf",
    )
    cf.file.save("Payment Form.pdf", ContentFile(FAKE_PDF), save=True)
    return cf


@pytest.mark.django_db
class TestListConferenceFiles:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-conference-files", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "name": "payment-form",
                "filename": "Payment Form.pdf",
                "size": len(FAKE_PDF),
                "create_time": approx_now(),
                "update_time": approx_now(),
            }
        ]

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

    def test_sorted_by_name(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        for name in ("instructions", "agreement", "payment-form"):
            cf = ConferenceFile.objects.create(
                conference=conference,
                name=name,
                filename=f"{name}.pdf",
            )
            cf.file.save(f"{name}.pdf", ContentFile(FAKE_PDF), save=True)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        names = [item["name"] for item in response.json()]
        assert names == ["agreement", "instructions", "payment-form"]

    def test_excludes_other_conferences(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,  # noqa: ARG002
    ) -> None:
        other = Conference.objects.create(
            name="other-conf",
            display_name="Other Conference",
        )
        other_cf = ConferenceFile.objects.create(
            conference=other,
            name="other-file",
            filename="Other.pdf",
        )
        other_cf.file.save("Other.pdf", ContentFile(FAKE_PDF), save=True)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()
        assert data["name"] == "payment-form"

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


@pytest.mark.django_db
class TestDownloadConferenceFile:
    @classmethod
    def path(cls, conference_name: str, conference_file_name: str) -> str:
        return reverse(
            "api-1.0.0:download-conference-file",
            args=[conference_name, conference_file_name],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.OK
        assert b"".join(response.streaming_content) == FAKE_PDF  # type: ignore[attr-defined]
        assert 'filename="Payment Form.pdf"' in response["Content-Disposition"]

    def test_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_wrong_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        other = Conference.objects.create(
            name="other-conf",
            display_name="Other Conference",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(other.name, conference_file.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        assert conference_file.file.name
        file_path = media_root / conference_file.file.name
        file_path.unlink()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        conference_file: ConferenceFile,
    ) -> None:
        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        conference: Conference,
        user: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        conference_file: ConferenceFile,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.fixture
def sample_pdf(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.pdf").read_bytes()
    return SimpleUploadedFile("upload.pdf", content, content_type="application/pdf")


@pytest.mark.django_db(transaction=True)
class TestUploadConferenceFile:
    @classmethod
    def path(cls, conference_name: str, conference_file_name: str) -> str:
        return reverse(
            "api-1.0.0:upload-conference-file",
            args=[conference_name, conference_file_name],
        )

    def test_creates_new_file(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["name"] == "payment-form"
        assert data["filename"] == "upload.pdf"
        assert data["size"] > 0
        assert data["create_time"] == approx_now()
        assert data["update_time"] == approx_now()

        assert ConferenceFile.objects.filter(
            conference=conference,
            name="payment-form",
        ).exists()

    def test_replaces_existing_file(
        self,
        client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        assert conference_file.file.name
        old_file_path = media_root / conference_file.file.name
        assert old_file_path.exists()

        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, conference_file.name),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == conference_file.name
        assert data["filename"] == "upload.pdf"

        assert not old_file_path.exists()

        assert (
            ConferenceFile.objects.filter(
                conference=conference,
                name=conference_file.name,
            ).count()
            == 1
        )

    def test_file_too_large_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.api.file.validate_upload",
            side_effect=FileTooLargeError("File size exceeds maximum allowed."),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "exceeds maximum" in response.json()["message"]

    def test_invalid_file_type_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.api.file.validate_upload",
            side_effect=InvalidFileTypeError("File type not allowed."),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "not allowed" in response.json()["message"]

    def test_invalid_filename_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.api.file.sanitize_filename",
            side_effect=ValueError("Filename is empty after sanitization."),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "empty after sanitization" in response.json()["message"]

    def test_cleans_up_file_on_pre_save_error(
        self,
        mocker: MockerFixture,
        client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch.object(
            Mutex,
            "lock_in_transaction",
            side_effect=RuntimeError("Unknown error"),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(pdf_files) == 0

    def test_cleans_up_file_on_database_error(
        self,
        mocker: MockerFixture,
        client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch.object(
            ConferenceFile,
            "save",
            side_effect=RuntimeError("DB error"),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(pdf_files) == 0

    def test_conference_not_found(
        self,
        client: Client,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path("nonexistent", "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        client: Client,
        user: User,
        conference: Conference,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(user)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        client: Client,
        conference: Conference,
        global_admin: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(global_admin)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_authorization_conference_chair(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_authorization_conference_secretary(
        self,
        client: Client,
        conference: Conference,
        conference_secretary: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_secretary)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_authorization_conference_reviewer_forbidden(
        self,
        client: Client,
        conference: Conference,
        conference_reviewer: User,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        client.force_login(conference_reviewer)

        response = client.post(
            self.path(conference.name, "payment-form"),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db(transaction=True)
class TestDeleteConferenceFile:
    @classmethod
    def path(cls, conference_name: str, conference_file_name: str) -> str:
        return reverse(
            "api-1.0.0:delete-conference-file",
            args=[conference_name, conference_file_name],
        )

    def test_happy_path(
        self,
        client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        assert conference_file.file.name
        file_path = media_root / conference_file.file.name
        assert file_path.exists()
        client.force_login(conference_chair)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not ConferenceFile.objects.filter(
            conference=conference,
            name=conference_file.name,
        ).exists()
        assert not file_path.exists()

    def test_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        client.force_login(conference_chair)

        response = client.delete(self.path(conference.name, "nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_wrong_conference(
        self,
        client: Client,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        other = Conference.objects.create(
            name="other-conf",
            display_name="Other Conference",
        )
        client.force_login(conference_chair)

        response = client.delete(self.path(other.name, conference_file.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        update_object(conference, active=False)
        client.force_login(conference_chair)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        conference_file: ConferenceFile,
    ) -> None:
        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        client: Client,
        user: User,
        conference: Conference,
        conference_file: ConferenceFile,
    ) -> None:
        client.force_login(user)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        client: Client,
        conference: Conference,
        global_admin: User,
        conference_file: ConferenceFile,
    ) -> None:
        client.force_login(global_admin)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_authorization_conference_chair(
        self,
        client: Client,
        conference: Conference,
        conference_chair: User,
        conference_file: ConferenceFile,
    ) -> None:
        client.force_login(conference_chair)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_authorization_conference_secretary(
        self,
        client: Client,
        conference: Conference,
        conference_secretary: User,
        conference_file: ConferenceFile,
    ) -> None:
        client.force_login(conference_secretary)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_authorization_conference_reviewer_forbidden(
        self,
        client: Client,
        conference: Conference,
        conference_reviewer: User,
        conference_file: ConferenceFile,
    ) -> None:
        client.force_login(conference_reviewer)

        response = client.delete(self.path(conference.name, conference_file.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

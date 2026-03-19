from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    PaperAuthor,
    PaperProof,
    PaperState,
    Track,
)
from app.conference.services import ProofService
from app.conference.services.proof import (
    ProofEligibilityError,
    RecipientDerivationError,
)
from app.core.models import User
from app.utils.files import InvalidFileTypeError
from tests.helpers import any_str, approx_now, update_object


@pytest.fixture(autouse=True)
def file_download_mode(settings: LazySettings) -> None:
    settings.FILE_DOWNLOAD_MODE = "django"


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.fixture
def eligible_paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
        announce_time=timezone.now(),
    )


@pytest.fixture
def proof(paper: Paper) -> PaperProof:
    return PaperProof.objects.create(
        paper=paper,
        recipient_name="Jane Doe",
        recipient_email="jane@example.com",
        file=SimpleUploadedFile(
            "proof.pdf",
            b"%PDF-proof-content",
            content_type="application/pdf",
        ),
    )


@pytest.fixture
def proof_without_file(paper: Paper) -> PaperProof:
    return PaperProof.objects.create(
        paper=paper,
        recipient_name="Jane Doe",
        recipient_email="jane@example.com",
    )


@pytest.mark.django_db
class TestListProofs:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-proofs", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        proof_without_file: PaperProof,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(proof_without_file.uid),
                "paper_code": "PAPER-001",
                "paper_title": "Test Paper",
                "recipient_name": "Jane Doe",
                "recipient_email": "jane@example.com",
                "comment": "",
                "proof_url": any_str,
                "create_time": approx_now(),
                "update_time": approx_now(),
            }
        ]

    def test_empty_list(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK
        assert response.json() == []

    def test_excludes_other_conferences(
        self,
        faker: Faker,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        proof_without_file: PaperProof,
    ) -> None:
        other = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(conference=other, display_name=faker.word())
        other_paper = Paper.objects.create(
            conference=other,
            track=other_track,
            owner=User.objects.create_user(username=faker.user_name()),
            code="OTHER-001",
            title="Other Paper",
        )
        PaperProof.objects.create(
            paper=other_paper,
            recipient_name="Other",
            recipient_email="other@example.com",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()
        assert data["uid"] == str(proof_without_file.uid)

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
        conference_chair: User,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(self, api_client: Client, conference: Conference) -> None:
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


@pytest.fixture
def proof_service_upsert(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ProofService, "upsert")


@pytest.mark.django_db
class TestUpsertProof:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:upsert-proof", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        PaperAuthor.objects.create(
            paper=eligible_paper,
            given_name="Jane",
            family_name="Doe",
            email="jane@example.com",
            corresponding=True,
            ordering=1,
        )
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": any_str,
            "paper_code": "PAPER-001",
            "paper_title": "Test Paper",
            "recipient_name": "Jane Doe",
            "recipient_email": "jane@example.com",
            "comment": "",
            "proof_url": any_str,
            "create_time": approx_now(),
            "update_time": approx_now(),
        }

        proof_service_upsert.assert_called_once_with(
            eligible_paper,
            recipient_name="",
            recipient_email="",
        )

    def test_explicit_overrides_forwarded(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={
                "recipient_name": "Override Name",
                "recipient_email": "override@example.com",
            },
        )
        assert response.status_code == HTTPStatus.OK

        proof_service_upsert.assert_called_once_with(
            eligible_paper,
            recipient_name="Override Name",
            recipient_email="override@example.com",
        )

    def test_eligibility_error_returns_400(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        proof_service_upsert.side_effect = ProofEligibilityError(
            "Paper is not in an accepted state."
        )
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "not in an accepted state" in response.json()["message"]

    def test_derivation_error_returns_422(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        proof_service_upsert.side_effect = RecipientDerivationError(["recipient_name"])
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "recipient_name" in response.json()["message"]

    def test_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        proof_service_upsert.assert_not_called()

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        eligible_paper: Paper,
        proof_service_upsert: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        proof_service_upsert.assert_not_called()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        eligible_paper: Paper,
        non_admin_role: ConferenceRole,
        proof_service_upsert: MagicMock,
    ) -> None:
        member = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=member,
            role=non_admin_role,
        )
        api_client.force_login(member)

        response = api_client.put(
            self.path(conference.name, eligible_paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        proof_service_upsert.assert_not_called()


@pytest.fixture
def proof_service_upload(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ProofService, "upload")


@pytest.fixture
def sample_pdf(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.pdf").read_bytes()
    return SimpleUploadedFile("proof.pdf", content, content_type="application/pdf")


@pytest.mark.django_db
class TestUploadProofFile:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:upload-proof-file",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        client: Client,
        conference_chair: User,
        conference: Conference,
        paper: Paper,
        proof_without_file: PaperProof,
        sample_pdf: SimpleUploadedFile,
        proof_service_upload: MagicMock,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(proof_without_file.uid)
        assert data["file_url"] == any_str

        proof_service_upload.assert_called_once()
        assert proof_service_upload.call_args.args[0] == proof_without_file
        assert proof_service_upload.call_args.args[1].name == "proof.pdf"

    def test_proof_not_found_returns_404(
        self,
        client: Client,
        conference_chair: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        proof_service_upload: MagicMock,
    ) -> None:
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        proof_service_upload.assert_not_called()

    def test_validation_error_returns_422(
        self,
        mocker: MockerFixture,
        client: Client,
        conference_chair: User,
        conference: Conference,
        paper: Paper,
        proof_without_file: PaperProof,  # noqa: ARG002
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        mocker.patch(
            "app.conference.services.proof.validate_upload",
            side_effect=InvalidFileTypeError("File type not allowed."),
        )
        client.force_login(conference_chair)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        assert "not allowed" in response.json()["message"]

    def test_unauthenticated(
        self,
        client: Client,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        proof_service_upload: MagicMock,
    ) -> None:
        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        proof_service_upload.assert_not_called()

    def test_unauthorized_user_forbidden(
        self,
        client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        proof_service_upload: MagicMock,
    ) -> None:
        client.force_login(user)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        proof_service_upload.assert_not_called()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_conference_non_admin_forbidden(
        self,
        faker: Faker,
        client: Client,
        conference: Conference,
        paper: Paper,
        sample_pdf: SimpleUploadedFile,
        non_admin_role: ConferenceRole,
        proof_service_upload: MagicMock,
    ) -> None:
        member = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=member,
            role=non_admin_role,
        )
        client.force_login(member)

        response = client.post(
            self.path(conference.name, paper.code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        proof_service_upload.assert_not_called()


@pytest.mark.django_db
class TestGetProof:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-proof", args=[uid])

    def test_happy_path(self, api_client: Client, proof: PaperProof) -> None:
        response = api_client.get(self.path(proof.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "paper_code": "PAPER-001",
            "paper_title": "Test Paper",
            "comment": "",
            "proof_url": any_str,
            "file_url": any_str,
        }

    def test_without_file(
        self,
        api_client: Client,
        proof_without_file: PaperProof,
    ) -> None:
        response = api_client.get(self.path(proof_without_file.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "file_url" not in data

    def test_with_confirmation(self, api_client: Client, proof: PaperProof) -> None:
        update_object(
            proof,
            confirmed_time=timezone.now(),
            comment="looks good",
            comment_time=timezone.now(),
        )

        response = api_client.get(self.path(proof.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["confirmed_time"] == approx_now()
        assert data["comment"] == "looks good"
        assert data["comment_time"] == approx_now()

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_excludes_admin_fields(
        self,
        api_client: Client,
        proof: PaperProof,
    ) -> None:
        response = api_client.get(self.path(proof.uid))
        data = response.json()

        assert "uid" not in data
        assert "recipient_name" not in data
        assert "recipient_email" not in data
        assert "notification_time" not in data
        assert "create_time" not in data
        assert "update_time" not in data


@pytest.fixture
def proof_service_confirm(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ProofService, "confirm")


@pytest.mark.django_db
class TestConfirmProof:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:confirm-proof", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        proof: PaperProof,
        proof_service_confirm: MagicMock,
    ) -> None:
        response = api_client.post(self.path(proof.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["confirmed_time"] == approx_now()
        assert data["paper_code"] == "PAPER-001"

        proof_service_confirm.assert_called_once()

    def test_not_found(
        self,
        api_client: Client,
        proof_service_confirm: MagicMock,
    ) -> None:
        response = api_client.post(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

        proof_service_confirm.assert_not_called()


@pytest.fixture
def proof_service_comment(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ProofService, "comment")


@pytest.mark.django_db
class TestCommentProof:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:comment-proof", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        proof: PaperProof,
        proof_service_comment: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(proof.uid),
            data={"comment": "page 3 has a broken formula"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["comment"] == "page 3 has a broken formula"
        assert data["comment_time"] == approx_now()

        proof_service_comment.assert_called_once()
        assert proof_service_comment.call_args.args[1] == "page 3 has a broken formula"

    def test_not_found(
        self,
        api_client: Client,
        proof_service_comment: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(ULID()),
            data={"comment": "some comment"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        proof_service_comment.assert_not_called()

    def test_missing_comment_returns_422(
        self,
        api_client: Client,
        proof: PaperProof,
        proof_service_comment: MagicMock,
    ) -> None:
        response = api_client.post(self.path(proof.uid), data={})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        proof_service_comment.assert_not_called()


@pytest.mark.django_db
class TestDownloadProofFile:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:download-proof-file", args=[uid])

    def test_happy_path(self, api_client: Client, proof: PaperProof) -> None:
        response = api_client.get(self.path(proof.uid))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/pdf"
        assert (
            response["Content-Disposition"] == 'inline; filename="PAPER-001-proof.pdf"'
        )
        assert b"".join(response.streaming_content) == b"%PDF-proof-content"  # type: ignore[attr-defined]

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_no_file_returns_not_found(
        self,
        api_client: Client,
        proof_without_file: PaperProof,
    ) -> None:
        response = api_client.get(self.path(proof_without_file.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_missing_file_on_disk_returns_not_found(
        self,
        api_client: Client,
        media_root: Path,
        proof: PaperProof,
    ) -> None:
        assert proof.file.name
        file_path = media_root / proof.file.name
        file_path.unlink()

        response = api_client.get(self.path(proof.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

from http import HTTPStatus
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from ulid import ULID

from app.conference.models import Conference, Paper, PaperFinal, PaperSubmission, Track
from app.core.models import User


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
def submission(paper: Paper) -> PaperSubmission:
    return PaperSubmission.objects.create(
        paper=paper,
        revision=1,
        file=SimpleUploadedFile(
            "submission.pdf",
            b"%PDF-test",
            content_type="application/pdf",
        ),
    )


@pytest.mark.django_db
class TestDownloadSubmission:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:download-submission", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        submission: PaperSubmission,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(submission.uid))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/pdf"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{submission.display_name}"'
        )
        assert b"".join(response.streaming_content) == b"%PDF-test"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("extension", "expected_content_type"),
        [
            (".pdf", "application/pdf"),
            (".doc", "application/msword"),
            (
                ".docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (".unknownext", "application/octet-stream"),
        ],
    )
    def test_content_type_detection(
        self,
        api_client: Client,
        user: User,
        paper: Paper,
        extension: str,
        expected_content_type: str,
    ) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file=SimpleUploadedFile(f"submission{extension}", b"test-content"),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(submission.uid))

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == expected_content_type

    def test_submission_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self, api_client: Client, submission: PaperSubmission
    ) -> None:
        response = api_client.get(self.path(submission.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        user: User,
        media_root: Path,
        submission: PaperSubmission,
    ) -> None:
        file_path = media_root / submission.file.name
        file_path.unlink()
        api_client.force_login(user)

        response = api_client.get(self.path(submission.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestDownloadSubmissionDecorated:
    @classmethod
    def path(cls, uid: ULID, filename: str) -> str:
        return reverse("api-1.0.0:download-submission-ex", args=[uid, filename])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        submission: PaperSubmission,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(submission.uid, "paper.pdf"))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/pdf"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{submission.display_name}"'
        )
        assert b"".join(response.streaming_content) == b"%PDF-test"  # type: ignore[attr-defined]

    def test_unauthenticated(
        self,
        api_client: Client,
        submission: PaperSubmission,
    ) -> None:
        response = api_client.get(self.path(submission.uid, "paper.pdf"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def final(paper: Paper) -> PaperFinal:
    return PaperFinal.objects.create(
        paper=paper,
        revision=1,
        source_file=SimpleUploadedFile(
            "source.zip",
            b"PK-test-zip",
            content_type="application/zip",
        ),
    )


@pytest.fixture
def final_with_viewable(paper: Paper) -> PaperFinal:
    return PaperFinal.objects.create(
        paper=paper,
        revision=1,
        source_file=SimpleUploadedFile(
            "source.zip",
            b"PK-test-zip",
            content_type="application/zip",
        ),
        viewable_file=SimpleUploadedFile(
            "viewable.pdf",
            b"%PDF-viewable",
            content_type="application/pdf",
        ),
    )


@pytest.mark.django_db
class TestDownloadFinal:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:download-final", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        final: PaperFinal,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/zip"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{final.display_name}"'
        )
        assert b"".join(response.streaming_content) == b"PK-test-zip"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("extension", "expected_content_type"),
        [
            (".zip", "application/zip"),
            (
                ".docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (".unknownext", "application/octet-stream"),
        ],
    )
    def test_content_type_detection(
        self,
        api_client: Client,
        user: User,
        paper: Paper,
        extension: str,
        expected_content_type: str,
    ) -> None:
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file=SimpleUploadedFile(f"source{extension}", b"test-content"),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid))

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == expected_content_type

    def test_final_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(self, api_client: Client, final: PaperFinal) -> None:
        response = api_client.get(self.path(final.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        user: User,
        media_root: Path,
        final: PaperFinal,
    ) -> None:
        file_path = media_root / final.source_file.name
        file_path.unlink()
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestDownloadFinalDecorated:
    @classmethod
    def path(cls, uid: ULID, filename: str) -> str:
        return reverse("api-1.0.0:download-final-ex", args=[uid, filename])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        final: PaperFinal,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid, "source.zip"))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/zip"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{final.display_name}"'
        )
        assert b"".join(response.streaming_content) == b"PK-test-zip"  # type: ignore[attr-defined]

    def test_unauthenticated(self, api_client: Client, final: PaperFinal) -> None:
        response = api_client.get(self.path(final.uid, "source.zip"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestDownloadFinalViewable:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:download-final-viewable", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        final_with_viewable: PaperFinal,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(final_with_viewable.uid))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/pdf"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{final_with_viewable.viewable_display_name}"'
        )
        assert b"".join(response.streaming_content) == b"%PDF-viewable"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("extension", "expected_content_type"),
        [
            (".pdf", "application/pdf"),
            (".doc", "application/msword"),
            (".unknownext", "application/octet-stream"),
        ],
    )
    def test_content_type_detection(
        self,
        api_client: Client,
        user: User,
        paper: Paper,
        extension: str,
        expected_content_type: str,
    ) -> None:
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file=SimpleUploadedFile("source.zip", b"test-content"),
            viewable_file=SimpleUploadedFile(f"viewable{extension}", b"viewable"),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid))

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == expected_content_type

    def test_final_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_viewable_file_empty_returns_not_found(
        self,
        api_client: Client,
        user: User,
        final: PaperFinal,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(final.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unauthenticated(
        self, api_client: Client, final_with_viewable: PaperFinal
    ) -> None:
        response = api_client.get(self.path(final_with_viewable.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        user: User,
        media_root: Path,
        final_with_viewable: PaperFinal,
    ) -> None:
        file_path = media_root / final_with_viewable.viewable_file.name
        file_path.unlink()
        api_client.force_login(user)

        response = api_client.get(self.path(final_with_viewable.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestDownloadFinalViewableDecorated:
    @classmethod
    def path(cls, uid: ULID, filename: str) -> str:
        return reverse("api-1.0.0:download-final-viewable-ex", args=[uid, filename])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        final_with_viewable: PaperFinal,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(final_with_viewable.uid, "viewable.pdf"))
        assert response.status_code == HTTPStatus.OK

        assert response["Content-Type"] == "application/pdf"
        assert (
            response["Content-Disposition"]
            == f'inline; filename="{final_with_viewable.viewable_display_name}"'
        )
        assert b"".join(response.streaming_content) == b"%PDF-viewable"  # type: ignore[attr-defined]

    def test_unauthenticated(
        self, api_client: Client, final_with_viewable: PaperFinal
    ) -> None:
        response = api_client.get(self.path(final_with_viewable.uid, "viewable.pdf"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

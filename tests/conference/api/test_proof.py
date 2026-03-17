from http import HTTPStatus
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from ulid import ULID

from app.conference.models import Conference, Paper, PaperProof, Track
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

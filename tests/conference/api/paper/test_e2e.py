from http import HTTPStatus
from pathlib import Path
from textwrap import dedent

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from app.conference.models import (
    AcceptanceLetter,
    CodePool,
    Conference,
    Keyword,
    Paper,
    PaperAuthor,
    PaperFinal,
    PaperState,
    Track,
    TrackVisibility,
)
from app.core.models import User
from tests.helpers import any_str, approx_now, extract_pdf_fonts, extract_pdf_text


@pytest.fixture(autouse=True)
def file_download_mode(settings: LazySettings) -> None:
    settings.FILE_DOWNLOAD_MODE = "django"


@pytest.fixture
def code_pool(conference: Conference) -> CodePool:
    return CodePool.objects.create(
        conference=conference,
        name="Main Pool",
        prefix="PAPER-",
    )


@pytest.fixture
def track(conference: Conference, code_pool: CodePool) -> Track:
    return Track.objects.create(
        conference=conference,
        code_pool=code_pool,
        display_name="Main Track",
        visibility=TrackVisibility.PUBLIC,
        submissions_enabled=True,
    )


@pytest.fixture
def sample_pdf(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.pdf").read_bytes()
    return SimpleUploadedFile("sample.pdf", content, content_type="application/pdf")


@pytest.fixture
def sample_zip(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.zip").read_bytes()
    return SimpleUploadedFile("source.zip", content, content_type="application/zip")


@pytest.mark.django_db
class TestPaperE2E:
    @classmethod
    def create_draft_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-draft", args=[conference_name])

    @classmethod
    def update_my_paper_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:update-my-paper",
            args=[conference_name, paper_code],
        )

    @classmethod
    def create_submission_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-my-submission",
            args=[conference_name, paper_code],
        )

    @classmethod
    def submit_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:submit-my-paper",
            args=[conference_name, paper_code],
        )

    @classmethod
    def unsubmit_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:unsubmit-my-paper",
            args=[conference_name, paper_code],
        )

    @classmethod
    def withdraw_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:withdraw-my-paper",
            args=[conference_name, paper_code],
        )

    @classmethod
    def decide_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:decide-paper",
            args=[conference_name, paper_code],
        )

    @classmethod
    def generate_acceptance_letter_path(
        cls,
        conference_name: str,
        paper_code: str,
    ) -> str:
        return reverse(
            "api-1.0.0:generate-acceptance-letter",
            args=[conference_name, paper_code],
        )

    @classmethod
    def announce_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:announce-papers", args=[conference_name])

    @classmethod
    def create_my_final_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-my-final",
            args=[conference_name, paper_code],
        )

    @classmethod
    def create_final_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-final",
            args=[conference_name, paper_code],
        )

    @classmethod
    def set_final_limit_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:set-paper-final-limit",
            args=[conference_name, paper_code],
        )

    def test_author_flow_submit_resubmit_withdraw(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        sample_pdf: SimpleUploadedFile,
    ) -> None:
        kw1 = Keyword.objects.create(text="Distributed Systems")
        kw2 = Keyword.objects.create(text="Databases")
        api_client.force_login(user)

        response = api_client.post(
            self.create_draft_path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Draft Title",
                "abstract": "Initial abstract.",
                "contribution": "Initial contribution.",
                "keywords": [kw1.text, kw2.text],
                "authors": [
                    {
                        "given_name": "Ada",
                        "family_name": "Lovelace",
                        "affiliation": "Analytical Engine Lab",
                        "region_code": "GB",
                        "email": "ada@example.com",
                        "phone": "+1000000000",
                        "corresponding": True,
                    }
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["state"] == PaperState.DRAFT
        assert data["keywords"] == sorted([kw1.text, kw2.text])
        assert "submission" not in data

        paper_code = data["code"]

        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_submission_path(conference.name, paper_code),
            data={"file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED
        submission = response.json()["submission"]
        assert submission["uid"] == any_str
        assert submission["display_name"] == f"{paper_code}.pdf"

        download_response = api_client.get(submission["download_url"])
        assert download_response.status_code == HTTPStatus.OK
        sample_pdf.seek(0)
        assert b"".join(download_response.streaming_content) == sample_pdf.read()  # type: ignore[attr-defined]

        response = api_client.post(self.submit_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == PaperState.SUBMITTED

        response = api_client.post(self.unsubmit_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == PaperState.DRAFT
        assert Paper.objects.get(code=paper_code).submit_time is None

        response = api_client.patch(
            self.update_my_paper_path(conference.name, paper_code),
            data={
                "title": "Revised Title",
                "abstract": "Revised abstract.",
                "contribution": "Revised contribution.",
                "keywords": [kw2.text],
                "authors": [
                    {
                        "given_name": "Ada",
                        "family_name": "Lovelace",
                        "affiliation": "Analytical Engine Lab",
                        "region_code": "GB",
                        "email": "ada.updated@example.com",
                        "phone": "+1000000000",
                        "corresponding": True,
                    }
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["title"] == "Revised Title"
        assert data["keywords"] == [kw2.text]

        response = api_client.post(self.submit_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == PaperState.SUBMITTED

        response = api_client.post(self.withdraw_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["state"] == "Withdrawn"
        assert data["withdraw_time"] is not None
        assert Paper.objects.get(code=paper_code).withdraw_time is not None

    def test_acceptance_and_announcement_flow(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        track: Track,
        user: User,
    ) -> None:
        paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="A Novel Approach to Distributed Systems",
            state=PaperState.SUBMITTED,
        )
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Alice",
            family_name="Smith",
            affiliation="University of Testing",
            ordering=0,
            corresponding=True,
        )
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Bob",
            family_name="Jones",
            affiliation="Institute of Science",
            ordering=1,
        )

        api_client.force_login(conference_chair)

        response = api_client.post(
            self.decide_path(conference.name, paper.code),
            data={"state": PaperState.ACCEPTED, "note": "Great work!"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == PaperState.ACCEPTED
        assert "acceptance_letter_url" not in response.json()

        template = dedent("""\
            #set text(font: "Inter")
            #let data = json(bytes(sys.inputs.at("data")))

            = Acceptance Letter

            Dear Authors,

            Your paper *#data.paper.title* (#data.paper.code) has been accepted
            to #data.conference.display_name in the #data.track.display_name track.

            == Authors

            #for author in data.paper.authors [
              - #author.given_name #author.family_name (#author.affiliation)
            ]
        """)

        response = api_client.post(
            self.generate_acceptance_letter_path(conference.name, paper.code),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["acceptance_letter_url"] == any_str

        acceptance_letter_url = data["acceptance_letter_url"]

        letter = AcceptanceLetter.objects.get(paper=paper)
        assert letter.template == template
        assert letter.rendered_pdf.name

        # Download the letter (unauthenticated, public URL).
        api_client.logout()

        response = api_client.get(acceptance_letter_url)
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"

        pdf_bytes = b"".join(response.streaming_content)  # type: ignore[attr-defined]
        text = extract_pdf_text(pdf_bytes)
        assert "Acceptance Letter" in text
        assert "A Novel Approach to Distributed Systems" in text
        assert "PAPER-001" in text
        assert "Alice Smith" in text
        assert "Bob Jones" in text
        assert any("Inter" in f for f in extract_pdf_fonts(pdf_bytes))

        # Regenerate with an updated template; the URL stays the same.
        api_client.force_login(conference_chair)

        updated_template = dedent("""\
            #let data = json(bytes(sys.inputs.at("data")))
            Updated letter for #data.paper.code.
        """)

        response = api_client.post(
            self.generate_acceptance_letter_path(conference.name, paper.code),
            data={"template": updated_template},
        )
        assert response.status_code == HTTPStatus.OK

        api_client.logout()

        response = api_client.get(acceptance_letter_url)
        assert response.status_code == HTTPStatus.OK

        pdf_bytes = b"".join(response.streaming_content)  # type: ignore[attr-defined]
        text = extract_pdf_text(pdf_bytes)
        assert "Updated letter for PAPER-001" in text

        # Announce the paper.
        api_client.force_login(conference_chair)

        assert paper.announce_time is None

        response = api_client.post(
            self.announce_path(conference.name),
            data={"codes": [paper.code]},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == [paper.code]

        paper.refresh_from_db()
        assert paper.announce_time == approx_now()

        # Second announce is idempotent.
        response = api_client.post(
            self.announce_path(conference.name),
            data={"codes": [paper.code]},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == []

    def test_final_upload_download_and_limit_management(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        track: Track,
        user: User,
        sample_pdf: SimpleUploadedFile,
        sample_zip: SimpleUploadedFile,
    ) -> None:
        paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-002",
            title="A Paper for Final Upload Testing",
            state=PaperState.ACCEPTED,
            final_revision_limit=1,
            announce_time=timezone.now(),
        )

        api_client.force_login(user)

        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_my_final_path(conference.name, paper.code),
            data={"source_file": sample_zip, "viewable_file": sample_pdf},
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["final"]["uid"] == any_str
        assert data["final"]["display_name"] == "PAPER-002.zip"
        assert data["final"]["viewable_display_name"] == "PAPER-002-viewable.pdf"
        assert data["final"]["download_url"] == any_str
        assert data["final"]["viewable_download_url"] == any_str
        assert data["final_revision_remaining"] == 0

        final_uid = data["final"]["uid"]

        download_response = api_client.get(data["final"]["download_url"])
        assert download_response.status_code == HTTPStatus.OK
        assert download_response["Content-Type"] == "application/zip"
        sample_zip.seek(0)
        assert b"".join(download_response.streaming_content) == sample_zip.read()  # type: ignore[attr-defined]

        viewable_response = api_client.get(data["final"]["viewable_download_url"])
        assert viewable_response.status_code == HTTPStatus.OK
        assert viewable_response["Content-Type"] == "application/pdf"
        sample_pdf.seek(0)
        assert b"".join(viewable_response.streaming_content) == sample_pdf.read()  # type: ignore[attr-defined]

        sample_zip.seek(0)
        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_my_final_path(conference.name, paper.code),
            data={"source_file": sample_zip},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "limit exceeded" in response.json()["message"]

        api_client.force_login(conference_chair)
        response = api_client.post(
            self.set_final_limit_path(conference.name, paper.code),
            data={"count": 3},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["final_revision_limit"] == 3
        assert data["final_revision_remaining"] == 2

        api_client.force_login(user)
        sample_zip.seek(0)
        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_my_final_path(conference.name, paper.code),
            data={"source_file": sample_zip},
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["final"]["uid"] != final_uid
        assert data["final_revision_remaining"] == 1

        assert PaperFinal.objects.filter(paper=paper).count() == 2

        api_client.force_login(conference_chair)
        sample_zip.seek(0)
        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_final_path(conference.name, paper.code),
            data={"source_file": sample_zip},
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["final_revision_remaining"] == 0

        sample_zip.seek(0)
        response = api_client.post.func(  # type: ignore[attr-defined]
            self.create_final_path(conference.name, paper.code),
            data={"source_file": sample_zip},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert data["final_revision_remaining"] == 0

        assert PaperFinal.objects.filter(paper=paper).count() == 4

from http import HTTPStatus
from pathlib import Path
from textwrap import dedent

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from app.conference.models import (
    AcceptanceLetter,
    CodePool,
    Conference,
    Keyword,
    Paper,
    PaperAuthor,
    PaperState,
    Track,
)
from app.core.models import User
from tests.helpers import any_str, approx_now


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
        visibility=Track.Visibility.PUBLIC,
        submissions_enabled=True,
    )


@pytest.fixture
def sample_pdf(test_data_dir: Path) -> SimpleUploadedFile:
    content = (test_data_dir / "sample.pdf").read_bytes()
    return SimpleUploadedFile("sample.pdf", content, content_type="application/pdf")


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

        template = dedent(
            """<html>
            <body>
            <h1>Acceptance Letter</h1>
            <p>Dear Authors,</p>
            <p>Your paper "{{ paper.title }}" ({{ paper.code }}) has been accepted.</p>
            <h2>Authors</h2>
            <ul>
            {% for author in paper.authors.all() -%}
            <li>{{ author.given_name }} {{ author.family_name }}</li>
            {% endfor -%}
            </ul>
            </body>
            </html>"""
        )

        response = api_client.post(
            self.generate_acceptance_letter_path(conference.name, paper.code),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["acceptance_letter_url"] == any_str

        acceptance_letter_url = data["acceptance_letter_url"]

        letter = AcceptanceLetter.objects.get(paper=paper)
        expected_html = dedent(
            """<html>
            <body>
            <h1>Acceptance Letter</h1>
            <p>Dear Authors,</p>
            <p>Your paper "A Novel Approach to Distributed Systems" (PAPER-001) has been accepted.</p>
            <h2>Authors</h2>
            <ul>
            <li>Alice Smith</li>
            <li>Bob Jones</li>
            </ul>
            </body>
            </html>"""  # noqa: E501
        )
        assert letter.rendered_html == expected_html

        api_client.logout()

        response = api_client.get(acceptance_letter_url)
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/html"
        assert response.content.decode() == expected_html

        api_client.force_login(conference_chair)

        updated_template = "<p>Updated: {{ paper.code }}</p>"
        response = api_client.post(
            self.generate_acceptance_letter_path(conference.name, paper.code),
            data={"template": updated_template},
        )
        assert response.status_code == HTTPStatus.OK

        api_client.logout()

        response = api_client.get(acceptance_letter_url)
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<p>Updated: PAPER-001</p>"

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

        response = api_client.post(
            self.announce_path(conference.name),
            data={"codes": [paper.code]},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == []

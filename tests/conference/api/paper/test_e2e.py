from http import HTTPStatus
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from app.conference.models import CodePool, Conference, Keyword, Paper, Track
from app.core.models import User
from tests.helpers import any_str


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
        assert data["state"] == Paper.State.DRAFT
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

        response = api_client.post(self.submit_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == Paper.State.SUBMITTED

        response = api_client.post(self.unsubmit_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == Paper.State.DRAFT
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
        assert response.json()["state"] == Paper.State.SUBMITTED

        response = api_client.post(self.withdraw_path(conference.name, paper_code))
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["state"] == "Withdrawn"
        assert data["withdraw_time"] is not None
        assert Paper.objects.get(code=paper_code).withdraw_time is not None

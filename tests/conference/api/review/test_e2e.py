from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    Paper,
    PaperState,
    PaperSubmission,
    ReviewState,
    Track,
)
from app.core.models import User


@pytest.fixture
def paper(
    faker: Faker,
    conference: Conference,
    track: Track,
    user: User,
) -> Paper:
    paper = Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code=f"PAPER-{faker.unique.random_int(1000, 9999)}",
        title=faker.sentence(),
        state=PaperState.SUBMITTED,
        submit_time=timezone.now(),
    )
    PaperSubmission.objects.create(
        paper=paper,
        revision=1,
        file="submission.pdf",
        uploader=user,
    )
    return paper


@pytest.mark.django_db(transaction=True)
class TestReviewE2E:
    @classmethod
    def assign_review_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:assign-review",
            args=[conference_name, paper_code],
        )

    @classmethod
    def list_my_reviews_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-my-reviews", args=[conference_name])

    @classmethod
    def accept_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse("api-1.0.0:accept-review", args=[conference_name, review_uid])

    @classmethod
    def update_my_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse("api-1.0.0:update-my-review", args=[conference_name, review_uid])

    @classmethod
    def submit_my_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse("api-1.0.0:submit-my-review", args=[conference_name, review_uid])

    @classmethod
    def list_reviews_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:list-reviews", args=[conference_name, paper_code])

    @classmethod
    def get_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse("api-1.0.0:get-review", args=[conference_name, review_uid])

    @classmethod
    def unsubmit_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse(
            "api-1.0.0:unsubmit-review",
            args=[conference_name, review_uid],
        )

    @classmethod
    def import_review_path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:import-review",
            args=[conference_name, paper_code],
        )

    @classmethod
    def update_review_path(cls, conference_name: str, review_uid: str) -> str:
        return reverse("api-1.0.0:update-review", args=[conference_name, review_uid])

    def test_reviewer_flow_with_admin_unsubmit(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        conference_reviewer: User,
    ) -> None:
        api_client.force_login(conference_chair)
        response = api_client.post(
            self.assign_review_path(conference.name, paper.code),
            data={"reviewer": str(conference_reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CREATED
        review_uid = response.json()["uid"]

        paper.refresh_from_db()
        assert paper.state == PaperState.UNDER_REVIEW

        api_client.logout()
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.list_my_reviews_path(conference.name))
        assert response.status_code == HTTPStatus.OK
        [review_data] = response.json()
        assert review_data["uid"] == review_uid
        assert review_data["state"] == ReviewState.PENDING

        response = api_client.post(self.accept_review_path(conference.name, review_uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == ReviewState.ACCEPTED

        response = api_client.patch(
            self.update_my_review_path(conference.name, review_uid),
            data={
                "originality": 4,
                "significance": 4,
                "technical": 4,
                "reference": 4,
                "presentation": 4,
                "match_topic": 4,
                "recommendation": 5,
                "contribution": "Clear contribution.",
                "decision_reason": "Accept with minor revisions.",
                "comments": "Nice work.",
                "confidential_remarks": "None.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        response = api_client.post(
            self.submit_my_review_path(conference.name, review_uid)
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["state"] == ReviewState.SUBMITTED
        assert data["submit_time"] is not None

        api_client.logout()
        api_client.force_login(conference_chair)

        response = api_client.get(self.list_reviews_path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK
        [review_data] = response.json()
        assert review_data["uid"] == review_uid
        assert review_data["state"] == ReviewState.SUBMITTED

        response = api_client.get(self.get_review_path(conference.name, review_uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == ReviewState.SUBMITTED

        response = api_client.post(
            self.unsubmit_review_path(conference.name, review_uid)
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == ReviewState.ACCEPTED

        api_client.logout()
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.submit_my_review_path(conference.name, review_uid)
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["state"] == ReviewState.SUBMITTED

    def test_offline_review_import_update_flow(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.import_review_path(conference.name, paper.code),
            data={
                "offline_reviewer_name": "External Reviewer",
                "originality": 3,
                "significance": 4,
                "technical": 3,
                "reference": 4,
                "presentation": 4,
                "match_topic": 3,
                "recommendation": 3,
                "contribution": "Solid external review.",
                "decision_reason": "Weak accept.",
                "comments": "Focus on clarity.",
                "confidential_remarks": "Imported from external system.",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        review_uid = response.json()["uid"]
        assert response.json()["submit_time"] is not None

        response = api_client.get(self.list_reviews_path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK
        [review_data] = response.json()
        assert review_data["uid"] == review_uid
        assert review_data["offline_reviewer_name"] == "External Reviewer"
        assert "reviewer" not in review_data

        response = api_client.get(self.get_review_path(conference.name, review_uid))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["offline_reviewer_name"] == "External Reviewer"
        assert "reviewer" not in response.json()

        response = api_client.patch(
            self.update_review_path(conference.name, review_uid),
            data={
                "decision_reason": "Updated after committee discussion.",
                "comments": "Clarify evaluation metrics.",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["decision_reason"] == "Updated after committee discussion."
        assert data["comments"] == "Clarify evaluation metrics."
        assert data["uid"] == review_uid

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from ulid import ULID

from app.conference.models import (
    Conference,
    Paper,
    PaperSubmission,
    Review,
    Track,
)
from app.core.models import User
from tests.helpers import any_str, update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(paper=paper, reviewer=user)


@pytest.mark.django_db
class TestGetMyReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-my-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        review: Review,
    ) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        update_object(
            review,
            state=Review.State.ACCEPTED,
            originality=4,
            significance=3,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="Good contribution",
            decision_reason="Accept because...",
            comments="Minor revisions needed",
            confidential_remarks="For chairs only",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(review.uid),
            "create_time": any_str,
            "paper": {
                "uid": str(paper.uid),
                "conference": conference.name,
                "track": {
                    "uid": str(paper.track.uid),
                    "display_name": paper.track.display_name,
                },
                "code": paper.code,
                "title": paper.title,
                "submission": {
                    "uid": str(submission.uid),
                    "display_name": f"{paper.code}.pdf",
                },
            },
            "state": Review.State.ACCEPTED,
            "originality": 4,
            "significance": 3,
            "technical": 5,
            "reference": 4,
            "presentation": 3,
            "match_topic": 5,
            "recommendation": 4,
            "contribution": "Good contribution",
            "decision_reason": "Accept because...",
            "comments": "Minor revisions needed",
            "confidential_remarks": "For chairs only",
        }

    def test_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_review_belongs_to_different_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(review, reviewer=other_user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_review_in_different_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        review: Review,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(other_conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_cancelled_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(review, state=Review.State.CANCELLED)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        review: Review,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_track_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        review: Review,
    ) -> None:
        update_object(track, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

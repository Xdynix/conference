from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    AdminComment,
    Conference,
    ConferenceVisibility,
    Paper,
    PaperState,
    Review,
    ReviewState,
    Track,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.mark.django_db
class TestListMyPaperFeedbacks:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:list-my-paper-feedbacks",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Great contribution.",
            decision_reason="Well written.",
            comments="Minor typos.",
        )
        AdminComment.objects.create(paper=paper, content="Please revise section 3.")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert len(data) == 2
        assert "Great contribution.\n\nWell written.\n\nMinor typos." in data
        assert "Please revise section 3." in data

    def test_accepted_revision_needed_state(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED_REVISION_NEEDED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Good work.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["Good work."]

    def test_empty_for_rejected_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.REJECTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="This should not be visible.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_empty_for_not_announced_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, state=PaperState.ACCEPTED, announce_time=None)
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="This should not be visible.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    @pytest.mark.parametrize(
        "state",
        [
            PaperState.DRAFT,
            PaperState.SUBMITTED,
            PaperState.UNDER_REVIEW,
        ],
    )
    def test_empty_for_non_decided_states(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_withdrawn_paper_still_sees_feedback(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
            withdraw_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Feedback for withdrawn paper.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == ["Feedback for withdrawn paper."]

    def test_only_submitted_reviews_included(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Submitted review.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.PENDING,
            contribution="Pending review.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.ACCEPTED,
            contribution="Accepted but not submitted.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.DECLINED,
            contribution="Declined review.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.CANCELLED,
            contribution="Cancelled review.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["Submitted review."]

    def test_empty_reviews_skipped(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="",
            decision_reason="",
            comments="",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Non-empty review.",
        )
        AdminComment.objects.create(
            paper=paper,
            content="",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["Non-empty review."]

    def test_review_text_fields_merged(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="First part.",
            decision_reason="Second part.",
            comments="Third part.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["First part.\n\nSecond part.\n\nThird part."]

    def test_partial_review_text_fields_merged(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Only contribution.",
            decision_reason="",
            comments="And comments.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["Only contribution.\n\nAnd comments."]

    def test_confidential_remarks_excluded(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Public feedback.",
            confidential_remarks="Secret remarks for admins only.",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data == ["Public feedback."]
        assert "Secret" not in str(data)

    def test_deterministic_order(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Review 1.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Review 2.",
        )
        AdminComment.objects.create(paper=paper, content="Comment 1.")
        AdminComment.objects.create(paper=paper, content="Comment 2.")
        api_client.force_login(user)

        response1 = api_client.get(self.path(conference.name, paper.code))
        response2 = api_client.get(self.path(conference.name, paper.code))

        assert response1.json() == response2.json()

    def test_order_stable_when_item_added(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Review 1.",
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Review 2.",
        )
        api_client.force_login(user)

        response_before = api_client.get(self.path(conference.name, paper.code))
        original_order = response_before.json()

        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            contribution="Review 3.",
        )

        response_after = api_client.get(self.path(conference.name, paper.code))
        new_order = response_after.json()

        original_indices = [new_order.index(item) for item in original_order]
        assert original_indices == sorted(original_indices)

    def test_no_feedback_returns_empty_list(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(
            paper,
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_accessible(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_track(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        update_object(track, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

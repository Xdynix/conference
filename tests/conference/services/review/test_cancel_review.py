from typing import Literal

import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, PaperState, Review, Track
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestCancelReview:
    @pytest.fixture
    def review(self, paper: Paper, user: User) -> Review:
        return Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.PENDING,
        )

    @pytest.mark.parametrize(
        "initial_state",
        [ReviewState.PENDING, ReviewState.ACCEPTED, ReviewState.SUBMITTED],
    )
    @pytest.mark.parametrize("mode", ["conference", "track"])
    def test_happy_path(
        self,
        review: Review,
        initial_state: ReviewState,
        mode: Literal["conference", "track"],
    ) -> None:
        update_object(review, state=initial_state)

        result = ReviewService.cancel_review(review, mode=mode)

        db_result = Review.objects.get(pk=result.pk)
        assert result.state == db_result.state == ReviewState.CANCELLED

    @pytest.mark.parametrize(
        "state",
        [ReviewState.DECLINED, ReviewState.CANCELLED],
    )
    def test_rejects_non_cancellable_state(
        self,
        review: Review,
        state: ReviewState,
    ) -> None:
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in pending, accepted, or submitted state to cancel",
        ):
            ReviewService.cancel_review(review, mode="conference")

        review.refresh_from_db()
        assert review.state == state

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.cancel_review(review, mode="conference")

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.cancel_review(review, mode="conference")

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.cancel_review(review, mode="conference")

    def test_track_mode_rejects_announced_paper(
        self,
        paper: Paper,
        review: Review,
    ) -> None:
        update_object(paper, state=PaperState.ACCEPTED, announce_time=timezone.now())

        with pytest.raises(
            InvalidReviewStateError,
            match="Cannot cancel reviews for papers after decision announcement",
        ):
            ReviewService.cancel_review(review, mode="track")

        review.refresh_from_db()
        assert review.state == ReviewState.PENDING

    def test_conference_mode_allows_announced_paper(
        self,
        paper: Paper,
        review: Review,
    ) -> None:
        update_object(paper, state=PaperState.ACCEPTED, announce_time=timezone.now())

        result = ReviewService.cancel_review(review, mode="conference")

        assert result.state == ReviewState.CANCELLED

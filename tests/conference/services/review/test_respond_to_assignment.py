from typing import Literal

import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Review, Track
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestRespondToAssignment:
    @pytest.fixture
    def review(self, paper: Paper, user: User) -> Review:
        return Review.objects.create(
            paper=paper,
            reviewer=user,
            state=Review.State.PENDING,
        )

    @pytest.mark.parametrize("response", [ReviewState.ACCEPTED, ReviewState.DECLINED])
    def test_accept_review(
        self,
        review: Review,
        response: Literal[ReviewState.ACCEPTED, ReviewState.DECLINED],
    ) -> None:
        result = ReviewService.respond_to_assignment(
            review=review,
            response=response,
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.state == db_result.state == response

    @pytest.mark.parametrize(
        "response",
        [
            state
            for state in ReviewState
            if state not in [ReviewState.ACCEPTED, ReviewState.DECLINED]
        ],
    )
    def test_invalid_response_raises_error(
        self,
        review: Review,
        response: ReviewState,
    ) -> None:
        with pytest.raises(ValueError, match="Invalid response"):
            ReviewService.respond_to_assignment(
                review=review,
                response=response,  # type: ignore[arg-type]
            )

        review.refresh_from_db()
        assert review.state == Review.State.PENDING

    @pytest.mark.parametrize("response", [ReviewState.ACCEPTED, ReviewState.DECLINED])
    @pytest.mark.parametrize(
        "state",
        [state for state in Review.State if state != Review.State.PENDING],
    )
    def test_non_pending_state_raises_error(
        self,
        review: Review,
        response: Literal[ReviewState.ACCEPTED, ReviewState.DECLINED],
        state: ReviewState,
    ) -> None:
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in pending state to respond",
        ):
            ReviewService.respond_to_assignment(review=review, response=response)

        review.refresh_from_db()
        assert review.state == state

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.respond_to_assignment(
                review=review,
                response=Review.State.ACCEPTED,
            )

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.respond_to_assignment(
                review=review,
                response=Review.State.ACCEPTED,
            )

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.respond_to_assignment(
                review=review,
                response=Review.State.ACCEPTED,
            )

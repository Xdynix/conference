import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Review, Track
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestUnsubmitReview:
    @pytest.fixture
    def review(self, paper: Paper, user: User) -> Review:
        return Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.SUBMITTED,
            submit_time=timezone.now(),
        )

    def test_happy_path(self, review: Review) -> None:
        result = ReviewService.unsubmit_review(review)

        db_result = Review.objects.get(pk=result.pk)
        assert result.state == db_result.state == ReviewState.ACCEPTED
        assert result.submit_time is None
        assert db_result.submit_time is None

    @pytest.mark.parametrize(
        "state",
        [state for state in ReviewState if state != ReviewState.SUBMITTED],
    )
    def test_rejects_non_submitted_state(
        self,
        review: Review,
        state: ReviewState,
    ) -> None:
        original_submit_time = review.submit_time
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in submitted state to unsubmit",
        ):
            ReviewService.unsubmit_review(review)

        review.refresh_from_db()
        assert review.state == state
        assert review.submit_time == original_submit_time

    def test_rejects_offline_review(self, paper: Paper) -> None:
        review = Review.objects.create(
            paper=paper,
            reviewer=None,
            state=ReviewState.SUBMITTED,
            submit_time=timezone.now(),
            offline_reviewer_name="Offline Reviewer",
        )

        with pytest.raises(
            InvalidReviewStateError,
            match="Offline reviews cannot be unsubmitted",
        ):
            ReviewService.unsubmit_review(review)

        review.refresh_from_db()
        assert review.state == ReviewState.SUBMITTED
        assert review.submit_time is not None

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.unsubmit_review(review)

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.unsubmit_review(review)

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.unsubmit_review(review)

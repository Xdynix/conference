import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Review, Track
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.services.review import (
    InvalidReviewStateError,
    ReviewSubmissionError,
)
from app.core.models import User
from tests.helpers import approx_now, update_object


@pytest.mark.django_db
class TestSubmitReview:
    @pytest.fixture
    def review(self, paper: Paper, user: User) -> Review:
        return Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.ACCEPTED,
            originality=5,
            significance=4,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="This paper presents a novel approach.",
            decision_reason="Accept due to strong technical contribution.",
        )

    def test_happy_path(self, review: Review) -> None:
        result = ReviewService.submit_review(review)

        db_result = Review.objects.get(pk=result.pk)
        assert result.state == db_result.state == ReviewState.SUBMITTED
        assert result.submit_time == db_result.submit_time == approx_now()

    def test_non_strict_mode_bypasses_validation(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        review = Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.ACCEPTED,
        )

        result = ReviewService.submit_review(review, strict=False)

        db_result = Review.objects.get(pk=result.pk)
        assert result.state == db_result.state == ReviewState.SUBMITTED
        assert result.submit_time == db_result.submit_time == approx_now()

    @pytest.mark.parametrize(
        "state",
        [state for state in ReviewState if state != ReviewState.ACCEPTED],
    )
    @pytest.mark.parametrize("strict", [True, False])
    def test_rejects_non_accepted_state(
        self,
        review: Review,
        state: ReviewState,
        strict: bool,
    ) -> None:
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in accepted state to submit",
        ):
            ReviewService.submit_review(review, strict=strict)

        review.refresh_from_db()
        assert review.state == state
        assert review.submit_time is None

    @pytest.mark.parametrize(
        "field",
        [
            "originality",
            "significance",
            "technical",
            "reference",
            "presentation",
            "match_topic",
            "recommendation",
        ],
    )
    def test_validates_score_field_required(self, review: Review, field: str) -> None:
        update_object(review, **{field: None})

        with pytest.raises(ReviewSubmissionError) as exc_info:
            ReviewService.submit_review(review)

        assert {field: "This field is required."} in exc_info.value.errors

        review.refresh_from_db()
        assert review.state == ReviewState.ACCEPTED
        assert review.submit_time is None

    @pytest.mark.parametrize(
        "field",
        ["contribution", "decision_reason"],
    )
    def test_validates_text_field_required(self, review: Review, field: str) -> None:
        update_object(review, **{field: ""})

        with pytest.raises(ReviewSubmissionError) as exc_info:
            ReviewService.submit_review(review)

        assert {field: "This field is required."} in exc_info.value.errors

        review.refresh_from_db()
        assert review.state == ReviewState.ACCEPTED
        assert review.submit_time is None

    @pytest.mark.parametrize(
        "field",
        ["comments", "confidential_remarks"],
    )
    def test_validates_text_field_optional(self, review: Review, field: str) -> None:
        update_object(review, **{field: ""})

        result = ReviewService.submit_review(review)

        assert result.state == ReviewState.SUBMITTED

    def test_collects_all_validation_errors(self, paper: Paper, user: User) -> None:
        review = Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.ACCEPTED,
        )

        with pytest.raises(ReviewSubmissionError) as exc_info:
            ReviewService.submit_review(review)

        errors = exc_info.value.errors
        assert len(errors) == 9
        assert {"originality": "This field is required."} in errors
        assert {"significance": "This field is required."} in errors
        assert {"technical": "This field is required."} in errors
        assert {"reference": "This field is required."} in errors
        assert {"presentation": "This field is required."} in errors
        assert {"match_topic": "This field is required."} in errors
        assert {"recommendation": "This field is required."} in errors
        assert {"contribution": "This field is required."} in errors
        assert {"decision_reason": "This field is required."} in errors

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.submit_review(review)

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.submit_review(review)

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.submit_review(review)

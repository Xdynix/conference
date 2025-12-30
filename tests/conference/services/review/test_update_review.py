import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, Review, Track
from app.conference.models.review import ReviewState
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=user,
        state=ReviewState.ACCEPTED,
    )


@pytest.mark.django_db
class TestUpdateReviewReviewerMode:
    def test_happy_path(self, review: Review) -> None:
        result = ReviewService.update_review(
            review,
            mode="reviewer",
            originality=5,
            significance=4,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="Novel approach to the problem.",
            decision_reason="Strong technical contribution.",
            comments="Minor typos in section 3.",
            confidential_remarks="Author is well-known in the field.",
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 5
        assert result.significance == db_result.significance == 4
        assert result.technical == db_result.technical == 5
        assert result.reference == db_result.reference == 4
        assert result.presentation == db_result.presentation == 3
        assert result.match_topic == db_result.match_topic == 5
        assert result.recommendation == db_result.recommendation == 4
        assert (
            result.contribution
            == db_result.contribution
            == "Novel approach to the problem."
        )
        assert (
            result.decision_reason
            == db_result.decision_reason
            == "Strong technical contribution."
        )
        assert result.comments == db_result.comments == "Minor typos in section 3."
        assert (
            result.confidential_remarks
            == db_result.confidential_remarks
            == "Author is well-known in the field."
        )

    def test_partial_update_scores_only(self, review: Review) -> None:
        result = ReviewService.update_review(
            review,
            mode="reviewer",
            originality=5,
            significance=4,
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 5
        assert result.significance == db_result.significance == 4
        assert result.technical == db_result.technical is None
        assert result.contribution == db_result.contribution == ""

    def test_partial_update_text_only(self, review: Review) -> None:
        result = ReviewService.update_review(
            review,
            mode="reviewer",
            contribution="Updated contribution.",
            comments="Updated comments.",
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.contribution == db_result.contribution == "Updated contribution."
        assert result.comments == db_result.comments == "Updated comments."
        assert result.originality == db_result.originality is None

    def test_preserves_existing_values(self, review: Review) -> None:
        update_object(
            review,
            originality=3,
            contribution="Original contribution.",
        )

        result = ReviewService.update_review(
            review,
            mode="reviewer",
            significance=4,
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 3
        assert result.contribution == db_result.contribution == "Original contribution."
        assert result.significance == db_result.significance == 4

    def test_no_changes_when_no_fields_provided(self, review: Review) -> None:
        update_object(review, originality=3, contribution="Original.")

        result = ReviewService.update_review(review, mode="reviewer")

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 3
        assert result.contribution == db_result.contribution == "Original."

    @pytest.mark.parametrize(
        "state",
        [state for state in ReviewState if state != ReviewState.ACCEPTED],
    )
    def test_rejects_non_accepted_state(
        self,
        review: Review,
        state: ReviewState,
    ) -> None:
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in accepted state to save draft",
        ):
            ReviewService.update_review(review, mode="reviewer", originality=5)

        review.refresh_from_db()
        assert review.state == state
        assert review.originality is None

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="reviewer", originality=5)

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="reviewer", originality=5)

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="reviewer", originality=5)


@pytest.mark.django_db
class TestUpdateReviewAdminMode:
    def test_happy_path_accepted_state(self, review: Review) -> None:
        result = ReviewService.update_review(
            review,
            mode="admin",
            originality=5,
            contribution="Admin edited contribution.",
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 5
        assert (
            result.contribution
            == db_result.contribution
            == "Admin edited contribution."
        )

    def test_happy_path_submitted_state(self, review: Review) -> None:
        update_object(review, state=ReviewState.SUBMITTED)

        result = ReviewService.update_review(
            review,
            mode="admin",
            originality=5,
            contribution="Admin edited submitted review.",
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 5
        assert (
            result.contribution
            == db_result.contribution
            == "Admin edited submitted review."
        )
        assert result.state == db_result.state == ReviewState.SUBMITTED

    @pytest.mark.parametrize(
        "state",
        [ReviewState.PENDING, ReviewState.DECLINED, ReviewState.CANCELLED],
    )
    def test_rejects_invalid_state(
        self,
        review: Review,
        state: ReviewState,
    ) -> None:
        update_object(review, state=state)

        with pytest.raises(
            InvalidReviewStateError,
            match="Review must be in accepted or submitted state to edit",
        ):
            ReviewService.update_review(review, mode="admin", originality=5)

        review.refresh_from_db()
        assert review.state == state
        assert review.originality is None

    def test_partial_update_preserves_existing(self, review: Review) -> None:
        update_object(
            review,
            state=ReviewState.SUBMITTED,
            originality=3,
            significance=4,
            contribution="Original contribution.",
        )

        result = ReviewService.update_review(
            review,
            mode="admin",
            significance=5,
        )

        db_result = Review.objects.get(pk=result.pk)
        assert result.originality == db_result.originality == 3
        assert result.significance == db_result.significance == 5
        assert result.contribution == db_result.contribution == "Original contribution."

    def test_inactive_conference_raises_error(
        self,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="admin", originality=5)

    def test_inactive_track_raises_error(self, track: Track, review: Review) -> None:
        update_object(track, active=False)

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="admin", originality=5)

    def test_deleted_paper_raises_error(self, paper: Paper, review: Review) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Review.DoesNotExist):
            ReviewService.update_review(review, mode="admin", originality=5)

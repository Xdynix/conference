import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Review,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ReviewService
from app.conference.services.paper import PaperStateError, PaperWithdrawnError
from app.conference.services.review import ReviewerNotEligibleError
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestAssignReviewer:
    @pytest.mark.parametrize("reviewer_role", ConferenceRole.reviewers())
    def test_conference_mode_assigns_reviewer_with_conference_role(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
        reviewer_role: ConferenceRole,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=reviewer,
            role=reviewer_role,
        )

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
            mode="conference",
        )

        db_review = Review.objects.get(pk=review.pk)
        assert review.paper_id == db_review.paper_id == paper.id
        assert review.reviewer_id == db_review.reviewer_id == reviewer.id
        assert review.assigner_id == db_review.assigner_id == assigner.id
        assert review.state == db_review.state == Review.State.PENDING
        assert (
            review.assignment_level
            == db_review.assignment_level
            == Review.AssignmentLevel.CONFERENCE
        )

    @pytest.mark.parametrize("reviewer_role", TrackRole.reviewers())
    def test_conference_mode_assigns_reviewer_with_track_role(
        self,
        faker: Faker,
        paper: Paper,
        reviewer_role: TrackRole,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=paper.track,
            user=reviewer,
            role=reviewer_role,
        )

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
            mode="conference",
        )

        db_review = Review.objects.get(pk=review.pk)
        assert review.reviewer_id == db_review.reviewer_id == reviewer.id
        assert (
            review.assignment_level
            == db_review.assignment_level
            == Review.AssignmentLevel.CONFERENCE
        )

    @pytest.mark.parametrize("reviewer_role", TrackRole.reviewers())
    def test_track_mode_assigns_reviewer_with_track_role(
        self,
        faker: Faker,
        paper: Paper,
        reviewer_role: TrackRole,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=paper.track,
            user=reviewer,
            role=reviewer_role,
        )

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
            mode="track",
        )

        assert review.reviewer == reviewer
        assert review.assignment_level == Review.AssignmentLevel.TRACK

    def test_conference_mode_can_assign_superuser(
        self,
        faker: Faker,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_superuser(username=faker.user_name())

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
            mode="conference",
        )

        assert review.reviewer == reviewer

    def test_conference_mode_can_assign_global_admin(
        self,
        faker: Faker,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=reviewer,
            role=GlobalRole.ADMIN,
        )

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
            mode="conference",
        )

        assert review.reviewer == reviewer

    def test_reviewer_without_conference_role_raises_error(
        self,
        faker: Faker,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Reviewer has no eligible role in the conference",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
                mode="conference",
            )

    def test_reviewer_without_track_role_raises_error(
        self,
        faker: Faker,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Reviewer has no eligible role in this track",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
                mode="track",
            )

    def test_reviewer_with_member_role_raises_error(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=reviewer,
            role=ConferenceRole.MEMBER,
        )

        with pytest.raises(ReviewerNotEligibleError):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
                mode="conference",
            )

    def test_track_mode_reviewer_from_other_track_raises_error(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        assigner = User.objects.create_user(username=faker.user_name())
        reviewer = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=other_track,
            user=reviewer,
            role=TrackRole.REVIEWER,
        )

        with pytest.raises(ReviewerNotEligibleError):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
                mode="track",
            )

    def test_paper_owner_cannot_be_assigned_as_reviewer(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=paper.owner,
            role=ConferenceRole.REVIEWER,
        )

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Paper owner cannot be assigned as reviewer",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=paper.owner,
                assigner=assigner,
                mode="conference",
            )

    def test_transitions_submitted_paper_to_under_review(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        assert paper.state == Paper.State.SUBMITTED

        ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=assigner,
            mode="conference",
        )

        paper.refresh_from_db()
        assert paper.state == Paper.State.UNDER_REVIEW

    def test_does_not_transition_under_review_paper(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        paper.state = Paper.State.UNDER_REVIEW
        paper.save()

        ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=assigner,
            mode="conference",
        )

        paper.refresh_from_db()
        assert paper.state == Paper.State.UNDER_REVIEW

    def test_draft_paper_raises_error(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        update_object(paper, state=Paper.State.DRAFT)

        with pytest.raises(
            PaperStateError,
            match="Cannot assign reviewers to papers in Draft state",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=conference_reviewer,
                assigner=assigner,
                mode="conference",
            )

    def test_withdrawn_paper_raises_error(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Cannot assign reviewers to withdrawn papers",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=conference_reviewer,
                assigner=assigner,
                mode="conference",
            )

    @pytest.mark.parametrize("state", Paper.State.decided())
    def test_announced_decided_paper_raises_error(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        update_object(paper, state=state, announce_time=timezone.now())

        with pytest.raises(
            PaperStateError,
            match="Cannot assign reviewers to papers after decision announcement",
        ):
            ReviewService.assign_reviewer(
                paper=paper,
                reviewer=conference_reviewer,
                assigner=assigner,
                mode="conference",
            )

    @pytest.mark.parametrize("state", Paper.State.decided())
    def test_unannounced_decided_paper_allows_assignment(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        update_object(paper, state=state, announce_time=None)

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=assigner,
            mode="conference",
        )

        assert review.reviewer == conference_reviewer
        paper.refresh_from_db()
        assert paper.state == state

    def test_under_review_paper_allows_assignment(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = User.objects.create_user(username=faker.user_name())
        update_object(paper, state=Paper.State.UNDER_REVIEW)

        review = ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=assigner,
            mode="conference",
        )

        assert review.reviewer == conference_reviewer

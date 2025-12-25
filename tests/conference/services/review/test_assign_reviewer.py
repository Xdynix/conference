import pytest
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
from app.conference.services.review import (
    AssignerNotAuthorizedError,
    ReviewerNotEligibleError,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.mark.django_db(transaction=True)
class TestAssignReviewer:
    @pytest.mark.parametrize("assigner_role", ConferenceRole.admins())
    @pytest.mark.parametrize("reviewer_role", ConferenceRole.reviewers())
    async def test_conference_admin_assigns_reviewer_with_conference_role(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
        assigner_role: ConferenceRole,
        reviewer_role: ConferenceRole,
    ) -> None:
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=assigner,
            role=assigner_role,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=reviewer,
            role=reviewer_role,
        )

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
        )

        db_review = await Review.objects.aget(pk=review.pk)
        assert review.paper_id == db_review.paper_id == paper.id
        assert review.reviewer_id == db_review.reviewer_id == reviewer.id
        assert review.assigner_id == db_review.assigner_id == assigner.id
        assert review.state == db_review.state == Review.State.PENDING
        assert (
            review.assignment_level
            == db_review.assignment_level
            == Review.AssignmentLevel.CONFERENCE
        )

    @pytest.mark.parametrize("assigner_role", ConferenceRole.admins())
    @pytest.mark.parametrize("reviewer_role", ConferenceRole.reviewers())
    async def test_conference_admin_assigns_reviewer_with_track_role(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
        assigner_role: ConferenceRole,
        reviewer_role: TrackRole,
    ) -> None:
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=assigner,
            role=assigner_role,
        )
        await TrackRoleAssignment.objects.acreate(
            track=paper.track,
            user=reviewer,
            role=reviewer_role,
        )

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
        )

        db_review = await Review.objects.aget(pk=review.pk)
        assert review.reviewer_id == db_review.reviewer_id == reviewer.id
        assert (
            review.assignment_level
            == db_review.assignment_level
            == Review.AssignmentLevel.CONFERENCE
        )

    @pytest.mark.parametrize("assigner_role", TrackRole.admins())
    @pytest.mark.parametrize("reviewer_role", TrackRole.reviewers())
    async def test_track_admin_assigns_reviewer_with_track_role(
        self,
        faker: Faker,
        paper: Paper,
        assigner_role: TrackRole,
        reviewer_role: TrackRole,
    ) -> None:
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=paper.track,
            user=assigner,
            role=assigner_role,
        )
        await TrackRoleAssignment.objects.acreate(
            track=paper.track,
            user=reviewer,
            role=reviewer_role,
        )

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=assigner,
        )

        assert review.reviewer == reviewer
        assert review.assignment_level == Review.AssignmentLevel.TRACK

    async def test_conference_admin_can_assign_superuser(
        self,
        faker: Faker,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        reviewer = await User.objects.acreate_superuser(username=faker.user_name())

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=conference_chair,
        )

        assert review.reviewer == reviewer

    async def test_conference_admin_can_assign_global_admin(
        self,
        faker: Faker,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(
            user=reviewer,
            role=GlobalRole.ADMIN,
        )

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=reviewer,
            assigner=conference_chair,
        )

        assert review.reviewer == reviewer

    async def test_superuser_can_assign(
        self,
        faker: Faker,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        assigner = await User.objects.acreate_superuser(username=faker.user_name())

        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=assigner,
        )

        assert review.assignment_level == Review.AssignmentLevel.CONFERENCE

    async def test_global_admin_can_assign(
        self,
        global_admin: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        review = await ReviewService.assign_reviewer(
            paper=paper,
            reviewer=conference_reviewer,
            assigner=global_admin,
        )

        assert review.assignment_level == Review.AssignmentLevel.CONFERENCE

    async def test_assigner_without_admin_role_raises_error(
        self,
        user: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        with pytest.raises(AssignerNotAuthorizedError):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=conference_reviewer,
                assigner=user,
            )

    async def test_reviewer_without_conference_role_raises_error(
        self,
        faker: Faker,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Reviewer has no eligible role in the conference",
        ):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=conference_chair,
            )

    async def test_reviewer_without_track_role_raises_error(
        self,
        faker: Faker,
        track: Track,
        paper: Paper,
    ) -> None:
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=assigner,
            role=TrackRole.CHAIR,
        )

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Reviewer has no eligible role in this track",
        ):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
            )

    async def test_reviewer_with_member_role_raises_error(
        self,
        faker: Faker,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=reviewer,
            role=ConferenceRole.MEMBER,
        )

        with pytest.raises(ReviewerNotEligibleError):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=conference_chair,
            )

    async def test_track_admin_cannot_assign_reviewer_from_other_track(
        self,
        faker: Faker,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        other_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=assigner,
            role=TrackRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=other_track,
            user=reviewer,
            role=TrackRole.REVIEWER,
        )

        with pytest.raises(ReviewerNotEligibleError):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
            )

    async def test_track_admin_cannot_assign_to_paper_in_other_track(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        other_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        other_paper = await Paper.objects.acreate(
            conference=conference,
            track=other_track,
            owner=user,
            code="OTHER-001",
            title="Other Paper",
        )
        assigner = await User.objects.acreate_user(username=faker.user_name())
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=assigner,
            role=TrackRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=other_track,
            user=reviewer,
            role=TrackRole.REVIEWER,
        )

        with pytest.raises(AssignerNotAuthorizedError):
            await ReviewService.assign_reviewer(
                paper=other_paper,
                reviewer=reviewer,
                assigner=assigner,
            )

    async def test_paper_owner_cannot_be_assigned_as_reviewer(
        self,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=paper.owner,
            role=ConferenceRole.REVIEWER,
        )

        with pytest.raises(
            ReviewerNotEligibleError,
            match="Paper owner cannot be assigned as reviewer",
        ):
            await ReviewService.assign_reviewer(
                paper=paper,
                reviewer=paper.owner,
                assigner=conference_chair,
            )

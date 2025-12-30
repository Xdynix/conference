import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Review,
    ReviewAssignmentLevel,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ReviewService
from app.core.models import User
from tests.helpers import a_update_object


@pytest.mark.django_db(transaction=True)
class TestReviewServiceVisibleReviews:
    async def test_superuser_sees_all_reviews(
        self,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        review = await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await a_update_object(user, is_superuser=True)

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == [review]

    async def test_global_admin_sees_all_reviews(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        review = await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )

        qs = await ReviewService.visible_reviews(
            conference=conference, user=global_admin
        )
        reviews = [r async for r in qs]

        assert reviews == [review]

    async def test_global_read_all_sees_all_reviews(
        self,
        global_read_all: User,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        review = await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )

        qs = await ReviewService.visible_reviews(
            conference=conference, user=global_read_all
        )
        reviews = [r async for r in qs]

        assert reviews == [review]

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_reviews(
        self,
        user: User,
        conference: Conference,
        paper: Paper,
        conference_role: ConferenceRole,
    ) -> None:
        conference_review = await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        track_review = await Review.objects.acreate(
            paper=paper,
            offline_reviewer_name="Offline Reviewer",
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=conference_role,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs.order_by("pk")]

        assert reviews == [conference_review, track_review]

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_only_track_level_reviews_in_their_track(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
        track_role: TrackRole,
    ) -> None:
        other_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        paper_in_track = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Paper in Track",
        )
        paper_in_other_track = await Paper.objects.acreate(
            conference=conference,
            track=other_track,
            owner=user,
            code="PAPER-002",
            title="Paper in Other Track",
        )
        track_review = await Review.objects.acreate(
            paper=paper_in_track,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        # Conference-level review in same track - should NOT be visible
        await Review.objects.acreate(
            paper=paper_in_track,
            offline_reviewer_name="Conference Reviewer",
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        # Track-level review in other track - should NOT be visible
        await Review.objects.acreate(
            paper=paper_in_other_track,
            offline_reviewer_name="Other Track Reviewer",
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=track_role,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == [track_review]

    async def test_track_admin_does_not_see_conference_level_reviews(
        self,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_track_admin_sees_reviews_from_multiple_administered_tracks(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        paper_a = await Paper.objects.acreate(
            conference=conference,
            track=track_a,
            owner=user,
            code="PAPER-A",
            title="Paper A",
        )
        paper_b = await Paper.objects.acreate(
            conference=conference,
            track=track_b,
            owner=user,
            code="PAPER-B",
            title="Paper B",
        )
        paper_c = await Paper.objects.acreate(
            conference=conference,
            track=track_c,
            owner=user,
            code="PAPER-C",
            title="Paper C",
        )
        review_a = await Review.objects.acreate(
            paper=paper_a,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        review_b = await Review.objects.acreate(
            paper=paper_b,
            offline_reviewer_name="Reviewer B",
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        # Review in track_c - not administered
        await Review.objects.acreate(
            paper=paper_c,
            offline_reviewer_name="Reviewer C",
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user,
            role=TrackRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user,
            role=TrackRole.SECRETARY,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs.order_by("paper__code")]

        assert reviews == [review_a, review_b]

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_track_non_admin_role_sees_no_reviews(
        self,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
        non_admin_role: TrackRole,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=non_admin_role,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    async def test_conference_non_admin_role_sees_no_reviews(
        self,
        user: User,
        conference: Conference,
        paper: Paper,
        non_admin_role: ConferenceRole,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=non_admin_role,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_user_without_roles_sees_no_reviews(
        self,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_excludes_deleted_paper_reviews(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        active_paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="ACTIVE-001",
            title="Active Paper",
        )
        deleted_paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="DELETED-001",
            title="Deleted Paper",
            delete_time=timezone.now(),
        )
        active_review = await Review.objects.acreate(
            paper=active_paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await Review.objects.acreate(
            paper=deleted_paper,
            offline_reviewer_name="Deleted Paper Reviewer",
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await a_update_object(user, is_superuser=True)

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == [active_review]

    async def test_excludes_inactive_conference_reviews(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await a_update_object(conference, active=False)

        qs = await ReviewService.visible_reviews(
            conference=conference, user=global_admin
        )
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_excludes_inactive_track_reviews(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )
        await a_update_object(track, active=False)

        qs = await ReviewService.visible_reviews(
            conference=conference, user=global_admin
        )
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_inactive_track_does_not_grant_visibility(
        self,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        await Review.objects.acreate(
            paper=paper,
            reviewer=user,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )
        await a_update_object(track, active=False)
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

    async def test_returns_empty_when_no_reviews(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        await a_update_object(user, is_superuser=True)

        qs = await ReviewService.visible_reviews(conference=conference, user=user)
        reviews = [r async for r in qs]

        assert reviews == []

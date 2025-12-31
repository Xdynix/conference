import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    Paper,
    PaperState,
    Review,
    ReviewAssignmentLevel,
    Track,
)
from app.conference.services import PaperService
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceRelocatePaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper Title",
        )

    @pytest.fixture
    def target_track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    def test_happy_path(
        self,
        paper: Paper,
        track: Track,
        target_track: Track,
    ) -> None:
        assert paper.track == track

        relocated = PaperService.relocate_paper(paper, target_track)

        db_relocated = Paper.objects.get(pk=relocated.pk)
        assert relocated.track == db_relocated.track == target_track

    def test_promotes_reviews_to_conference_level(
        self,
        faker: Faker,
        paper: Paper,
        target_track: Track,
    ) -> None:
        reviewer = User.objects.create_user(username=faker.user_name())
        review = Review.objects.create(
            paper=paper,
            reviewer=reviewer,
            assignment_level=ReviewAssignmentLevel.TRACK,
        )

        PaperService.relocate_paper(paper, target_track)

        review.refresh_from_db()
        assert review.assignment_level == ReviewAssignmentLevel.CONFERENCE

    def test_promotes_multiple_reviews(
        self,
        faker: Faker,
        paper: Paper,
        target_track: Track,
    ) -> None:
        reviews = [
            Review.objects.create(
                paper=paper,
                reviewer=User.objects.create_user(username=faker.user_name()),
                assignment_level=ReviewAssignmentLevel.TRACK,
            )
            for _ in range(3)
        ]

        PaperService.relocate_paper(paper, target_track)

        for review in reviews:
            review.refresh_from_db()
            assert review.assignment_level == ReviewAssignmentLevel.CONFERENCE

    def test_conference_level_reviews_unchanged(
        self,
        faker: Faker,
        paper: Paper,
        target_track: Track,
    ) -> None:
        reviewer = User.objects.create_user(username=faker.user_name())
        review = Review.objects.create(
            paper=paper,
            reviewer=reviewer,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
        )

        PaperService.relocate_paper(paper, target_track)

        review.refresh_from_db()
        assert review.assignment_level == ReviewAssignmentLevel.CONFERENCE

    def test_raises_when_target_track_inactive(
        self,
        paper: Paper,
        target_track: Track,
    ) -> None:
        update_object(target_track, active=False)

        with pytest.raises(ValueError, match="Target track is not active"):
            PaperService.relocate_paper(paper, target_track)

    def test_raises_when_target_track_different_conference(
        self,
        faker: Faker,
        paper: Paper,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )

        with pytest.raises(ValueError, match="Target track must be in the same"):
            PaperService.relocate_paper(paper, other_track)

    def test_raises_when_target_track_same_as_current(
        self,
        paper: Paper,
        track: Track,
    ) -> None:
        with pytest.raises(ValueError, match="Target track must be different"):
            PaperService.relocate_paper(paper, track)

    def test_raises_when_paper_deleted(
        self,
        paper: Paper,
        target_track: Track,
    ) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.relocate_paper(paper, target_track)

    @pytest.mark.parametrize("state", PaperState)
    def test_can_relocate_from_any_state(
        self,
        paper: Paper,
        target_track: Track,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)

        relocated = PaperService.relocate_paper(paper, target_track)

        assert relocated.track == target_track
        assert relocated.state == state

    def test_can_relocate_withdrawn_paper(
        self,
        paper: Paper,
        target_track: Track,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())

        relocated = PaperService.relocate_paper(paper, target_track)

        assert relocated.track == target_track

from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    PaperSubmission,
    Profile,
    Review,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.models.review import ReviewAssignmentLevel, ReviewState
from app.conference.services import PaperService, ReviewService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import any_str, update_object


def create_review(
    paper: Paper,
    *,
    reviewer: User | None = None,
    state: ReviewState = ReviewState.PENDING,
    assignment_level: ReviewAssignmentLevel = ReviewAssignmentLevel.CONFERENCE,
    assigner: User | None = None,
    offline_reviewer_name: str = "",
) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=reviewer,
        state=state,
        assignment_level=assignment_level,
        assigner=assigner,
        offline_reviewer_name=offline_reviewer_name,
    )


@pytest.mark.django_db
class TestListMyReviews:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-my-reviews", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        review = create_review(paper, reviewer=user, state=Review.State.ACCEPTED)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(review.uid),
                "create_time": any_str,
                "paper": {
                    "uid": str(paper.uid),
                    "conference": conference.name,
                    "track": {
                        "uid": str(paper.track.uid),
                        "display_name": paper.track.display_name,
                    },
                    "code": paper.code,
                    "title": paper.title,
                    "submission": {
                        "uid": str(submission.uid),
                        "display_name": f"{paper.code}.pdf",
                    },
                },
                "state": Review.State.ACCEPTED,
            },
        ]

    def test_returns_only_reviews_assigned_to_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        user_review = create_review(paper, reviewer=user)
        create_review(paper, reviewer=other_user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [review_data] = response.json()
        assert review_data["uid"] == str(user_review.uid)

    def test_scoped_to_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        other_paper = Paper.objects.create(
            conference=other_conference,
            track=other_track,
            owner=user,
            code="OTHER-001",
            title="Other Paper",
        )
        review_in_conference = create_review(paper, reviewer=user)
        create_review(other_paper, reviewer=user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        [review_data] = response.json()
        assert review_data["uid"] == str(review_in_conference.uid)

    def test_excludes_deleted_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        create_review(paper, reviewer=user)
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_excludes_cancelled_reviews(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        create_review(paper, reviewer=user, state=Review.State.CANCELLED)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_returns_empty_list_when_no_reviews(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(ReviewService, "visible_reviews")


@pytest.mark.django_db
class TestListReviews:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:list-reviews",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        reviewer = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(
            user=reviewer,
            given_name="Alice",
            family_name="Smith",
            affiliation="University",
            region_code=Region.US.name,
        )
        Profile.objects.create(
            user=conference_chair,
            given_name="Bob",
            family_name="Admin",
            affiliation="Organization",
        )
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        review = create_review(
            paper,
            reviewer=reviewer,
            state=Review.State.SUBMITTED,
            assigner=conference_chair,
            assignment_level=Review.AssignmentLevel.CONFERENCE,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(review.uid),
                "create_time": any_str,
                "paper": {
                    "uid": str(paper.uid),
                    "conference": conference.name,
                    "track": {
                        "uid": str(paper.track.uid),
                        "display_name": paper.track.display_name,
                    },
                    "code": paper.code,
                    "title": paper.title,
                    "submission": {
                        "uid": str(submission.uid),
                        "display_name": f"{paper.code}.pdf",
                    },
                },
                "state": Review.State.SUBMITTED,
                "reviewer": {
                    "uid": str(reviewer.uid),
                    "email": reviewer.email,
                    "profile": {
                        "given_name": "Alice",
                        "family_name": "Smith",
                        "affiliation": "University",
                        "region_code": "US",
                    },
                },
                "offline_reviewer_name": "",
                "assigner": {
                    "uid": str(conference_chair.uid),
                    "email": "",
                    "profile": {
                        "given_name": "Bob",
                        "family_name": "Admin",
                        "affiliation": "Organization",
                        "region_code": "",
                    },
                },
                "assignment_level": Review.AssignmentLevel.CONFERENCE,
            },
        ]

        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)
        mock_visible_reviews.assert_awaited_once_with(
            conference=conference,
            user=conference_chair,
        )

    def test_offline_review(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review = create_review(
            paper,
            reviewer=None,
            offline_reviewer_name="External Reviewer",
            state=Review.State.SUBMITTED,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        [review_data] = response.json()
        assert "reviewer" not in review_data
        assert review_data["offline_reviewer_name"] == "External Reviewer"

    def test_returns_empty_list_when_no_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_authorization_track_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.FORBIDDEN

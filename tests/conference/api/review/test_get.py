from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

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
from app.conference.services import ReviewService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(paper=paper, reviewer=user)


@pytest.mark.django_db
class TestGetMyReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-my-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        review: Review,
    ) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        update_object(
            review,
            state=Review.State.ACCEPTED,
            originality=4,
            significance=3,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="Good contribution",
            decision_reason="Accept because...",
            comments="Minor revisions needed",
            confidential_remarks="For chairs only",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
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
            "originality": 4,
            "significance": 3,
            "technical": 5,
            "reference": 4,
            "presentation": 3,
            "match_topic": 5,
            "recommendation": 4,
            "contribution": "Good contribution",
            "decision_reason": "Accept because...",
            "comments": "Minor revisions needed",
            "confidential_remarks": "For chairs only",
        }

    def test_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_review_belongs_to_different_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(review, reviewer=other_user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_review_in_different_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        review: Review,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(other_conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_cancelled_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(review, state=Review.State.CANCELLED)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        review: Review,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_track_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        review: Review,
    ) -> None:
        update_object(track, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(ReviewService, "visible_reviews")


@pytest.mark.django_db
class TestGetReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:get-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
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
        review = Review.objects.create(
            paper=paper,
            reviewer=reviewer,
            state=Review.State.SUBMITTED,
            assigner=conference_chair,
            assignment_level=Review.AssignmentLevel.CONFERENCE,
            originality=4,
            significance=3,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="Good contribution",
            decision_reason="Accept because...",
            comments="Minor revisions needed",
            confidential_remarks="For chairs only",
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
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
                    "region_code": "",
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
            "originality": 4,
            "significance": 3,
            "technical": 5,
            "reference": 4,
            "presentation": 3,
            "match_topic": 5,
            "recommendation": 4,
            "contribution": "Good contribution",
            "decision_reason": "Accept because...",
            "comments": "Minor revisions needed",
            "confidential_remarks": "For chairs only",
        }

        mock_visible_reviews.assert_awaited_once_with(
            conference=conference,
            user=conference_chair,
        )

    def test_review_not_visible(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review = Review.objects.create(paper=paper, reviewer=None)
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_review_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        mock_visible_reviews: AsyncMock,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        review = Review.objects.create(paper=paper, reviewer=None)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        mock_visible_reviews: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        review = Review.objects.create(paper=paper, reviewer=None)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        mock_visible_reviews: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        review = Review.objects.create(paper=paper, reviewer=None)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, review.uid))
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

        response = api_client.get(self.path(conference.name, ULID()))
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

        response = api_client.get(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

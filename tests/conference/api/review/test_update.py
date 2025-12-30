from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

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
    Review,
    ReviewAssignmentLevel,
    ReviewState,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=user,
        state=ReviewState.ACCEPTED,
    )


@pytest.fixture
def review_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ReviewService, "update_review")


@pytest.mark.django_db
class TestUpdateMyReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-my-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_update: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={
                "originality": 5,
                "significance": 4,
                "technical": 5,
                "reference": 4,
                "presentation": 3,
                "match_topic": 5,
                "recommendation": 4,
                "contribution": "Novel approach.",
                "decision_reason": "Strong contribution.",
                "comments": "Minor typos.",
                "confidential_remarks": "For chairs.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(review.uid),
            "create_time": any_str,
            "paper": {
                "uid": str(review.paper.uid),
                "conference": conference.name,
                "track": {
                    "uid": str(review.paper.track.uid),
                    "display_name": review.paper.track.display_name,
                },
                "code": review.paper.code,
                "title": review.paper.title,
            },
            "state": ReviewState.ACCEPTED,
            "originality": 5,
            "significance": 4,
            "technical": 5,
            "reference": 4,
            "presentation": 3,
            "match_topic": 5,
            "recommendation": 4,
            "contribution": "Novel approach.",
            "decision_reason": "Strong contribution.",
            "comments": "Minor typos.",
            "confidential_remarks": "For chairs.",
        }

        review_service_update.assert_called_once_with(
            review,
            mode="reviewer",
            originality=5,
            significance=4,
            technical=5,
            reference=4,
            presentation=3,
            match_topic=5,
            recommendation=4,
            contribution="Novel approach.",
            decision_reason="Strong contribution.",
            comments="Minor typos.",
            confidential_remarks="For chairs.",
        )

    def test_partial_update(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_update: MagicMock,
    ) -> None:
        update_object(
            review,
            originality=3,
            contribution="Original contribution.",
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"significance": 4},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["originality"] == 3
        assert data["significance"] == 4
        assert data["contribution"] == "Original contribution."

        review_service_update.assert_called_once_with(
            review,
            mode="reviewer",
            significance=4,
        )

    def test_empty_payload(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_update: MagicMock,
    ) -> None:
        update_object(review, originality=3)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["originality"] == 3

        review_service_update.assert_called_once_with(
            review,
            mode="reviewer",
        )

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_update: MagicMock,
    ) -> None:
        review_service_update.side_effect = InvalidReviewStateError(
            "Review must be in accepted state to save draft."
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "accepted state to save draft" in response.json()["message"]

    def test_validates_score_range(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 6},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(other_conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_cancelled_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
    ) -> None:
        update_object(review, state=ReviewState.CANCELLED)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path("nonexistent", ULID()),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(ReviewService, "visible_reviews")


@pytest.mark.django_db
class TestUpdateReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:update-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={
                "originality": 5,
                "significance": 4,
                "contribution": "Admin edited.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(review.uid),
            "create_time": any_str,
            "paper": {
                "uid": str(review.paper.uid),
                "conference": conference.name,
                "track": {
                    "uid": str(review.paper.track.uid),
                    "display_name": review.paper.track.display_name,
                },
                "code": review.paper.code,
                "title": review.paper.title,
            },
            "state": ReviewState.ACCEPTED,
            "reviewer": {
                "uid": str(user.uid),
                "email": user.email,
            },
            "offline_reviewer_name": "",
            "assignment_level": ReviewAssignmentLevel.CONFERENCE,
            "originality": 5,
            "significance": 4,
            "contribution": "Admin edited.",
            "decision_reason": "",
            "comments": "",
            "confidential_remarks": "",
        }

        review_service_update.assert_called_once_with(
            review,
            mode="admin",
            originality=5,
            significance=4,
            contribution="Admin edited.",
        )
        mock_visible_reviews.assert_awaited_once_with(
            conference=conference,
            user=conference_chair,
        )

    def test_partial_update(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        update_object(
            review,
            originality=3,
            contribution="Original.",
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"significance": 5},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["originality"] == 3
        assert data["significance"] == 5
        assert data["contribution"] == "Original."

        review_service_update.assert_called_once()

    def test_empty_payload(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        update_object(review, originality=3)
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["originality"] == 3

        review_service_update.assert_called_once()

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review_service_update.side_effect = InvalidReviewStateError(
            "Review must be in accepted or submitted state to edit."
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "accepted or submitted state to edit" in response.json()["message"]

    def test_validates_score_range(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 0},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_review_not_visible(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
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

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path("nonexistent", ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.OK

        review_service_update.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        review: Review,
        review_service_update: MagicMock,
        mock_visible_reviews: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(admin)

        response = api_client.patch(
            self.path(conference.name, review.uid),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.OK

        review_service_update.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        api_client.force_login(admin)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

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

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"originality": 5},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

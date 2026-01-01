from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Paper,
    Review,
    ReviewState,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=user,
        state=ReviewState.PENDING,
    )


@pytest.fixture
def review_service_respond(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ReviewService, "respond_to_assignment")


@pytest.mark.django_db
class TestAcceptReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:accept-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_respond: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == ReviewState.ACCEPTED

        review_service_respond.assert_called_once_with(
            review=review,
            response=ReviewState.ACCEPTED,
        )

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_respond: MagicMock,
    ) -> None:
        review_service_respond.side_effect = InvalidReviewStateError(
            "Review must be in pending state to respond."
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "pending state" in response.json()["message"]

    def test_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, ULID()))
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

        response = api_client.post(self.path(conference.name, review.uid))
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
            visibility=ConferenceVisibility.PUBLIC,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(other_conference.name, review.uid))
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

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestDeclineReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:decline-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_respond: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == ReviewState.DECLINED

        review_service_respond.assert_called_once_with(
            review=review,
            response=ReviewState.DECLINED,
        )

    def test_invalid_state_returns_bad_request(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_respond: MagicMock,
    ) -> None:
        review_service_respond.side_effect = InvalidReviewStateError(
            "Review must be in pending state to respond."
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "pending state" in response.json()["message"]

    def test_review_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, ULID()))
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

        response = api_client.post(self.path(conference.name, review.uid))
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
            visibility=ConferenceVisibility.PUBLIC,
        )
        api_client.force_login(user)

        response = api_client.post(self.path(other_conference.name, review.uid))
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

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(ReviewService, "visible_reviews")


@pytest.fixture
def review_service_cancel(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ReviewService, "cancel_review")


@pytest.mark.django_db
class TestCancelReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:cancel-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_cancel: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        def cancel_side_effect(r: Review) -> Review:
            r.state = ReviewState.CANCELLED
            r.save(update_fields=["state"])
            return r

        review_service_cancel.side_effect = cancel_side_effect
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == ReviewState.CANCELLED
        assert "assignment_level" in data

        review_service_cancel.assert_called_once_with(review)
        mock_visible_reviews.assert_awaited_once_with(
            conference=conference,
            user=conference_chair,
        )

    def test_handle_review_state_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_cancel: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review_service_cancel.side_effect = InvalidReviewStateError(
            "Review must be in pending, accepted, or submitted state to cancel."
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "pending, accepted, or submitted state" in response.json()["message"]

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

        response = api_client.post(self.path(conference.name, review.uid))
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

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        review: Review,
        review_service_cancel: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        review_service_cancel.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        review: Review,
        review_service_cancel: MagicMock,
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

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        review_service_cancel.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        review: Review,
        review_service_cancel: MagicMock,
        mock_visible_reviews: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(admin)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        review_service_cancel.assert_called_once()

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

        response = api_client.post(self.path(conference.name, ULID()))
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

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN

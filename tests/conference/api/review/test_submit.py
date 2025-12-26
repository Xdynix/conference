from http import HTTPStatus
from typing import Any
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
    Paper,
    Review,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ReviewService
from app.conference.services.review import (
    InvalidReviewStateError,
    ReviewSubmissionError,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=user,
        state=Review.State.ACCEPTED,
    )


@pytest.fixture
def review_service_submit(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ReviewService, "submit_review")


@pytest.mark.django_db
class TestSubmitMyReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:submit-my-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_submit: MagicMock,
    ) -> None:
        def submit_side_effect(r: Review, *_: Any, **__: Any) -> Review:
            r.state = Review.State.SUBMITTED
            r.save(update_fields=["state"])
            return r

        review_service_submit.side_effect = submit_side_effect
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == Review.State.SUBMITTED
        assert "assignment_level" not in data

        review_service_submit.assert_called_once_with(review, strict=True)

    def test_handle_review_state_error(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_submit: MagicMock,
    ) -> None:
        review_service_submit.side_effect = InvalidReviewStateError(
            "Review must be in accepted state to submit."
        )
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "accepted state" in response.json()["message"]

    def test_handle_review_validation_errors(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        review: Review,
        review_service_submit: MagicMock,
    ) -> None:
        errors = [
            {"originality": "This field is required."},
            {"significance": "This field is required."},
            {"contribution": "This field is required."},
        ]
        review_service_submit.side_effect = ReviewSubmissionError(errors)
        api_client.force_login(user)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json() == {
            "message": "Review submission validation failed.",
            "details": [
                {"originality": "This field is required."},
                {"significance": "This field is required."},
                {"contribution": "This field is required."},
            ],
        }

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
            visibility=Conference.Visibility.PUBLIC,
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
        update_object(review, state=Review.State.CANCELLED)
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


@pytest.mark.django_db
class TestSubmitReview:
    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:submit-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_submit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        def submit_side_effect(r: Review, *_: Any, **__: Any) -> Review:
            r.state = Review.State.SUBMITTED
            r.save(update_fields=["state"])
            return r

        review_service_submit.side_effect = submit_side_effect
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == Review.State.SUBMITTED
        assert "assignment_level" in data

        review_service_submit.assert_called_once_with(review, strict=False)
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
        review_service_submit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review_service_submit.side_effect = InvalidReviewStateError(
            "Review must be in accepted state to submit."
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "accepted state" in response.json()["message"]

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
        review_service_submit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        review_service_submit.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        review: Review,
        review_service_submit: MagicMock,
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

        review_service_submit.assert_called_once()

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

        response = api_client.post(self.path(conference.name, ULID()))
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

        response = api_client.post(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.fixture
def review_service_unsubmit(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(ReviewService, "unsubmit_review")


@pytest.mark.django_db
class TestUnsubmitReview:
    @pytest.fixture(autouse=True)
    def review(self, review: Review) -> Review:
        update_object(review, state=Review.State.SUBMITTED)
        return review

    @classmethod
    def path(cls, conference_name: str, review_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:unsubmit-review",
            args=[conference_name, review_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        review: Review,
        review_service_unsubmit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        def unsubmit_side_effect(r: Review) -> Review:
            r.state = Review.State.ACCEPTED
            r.submit_time = None
            r.save(update_fields=["state", "submit_time"])
            return r

        review_service_unsubmit.side_effect = unsubmit_side_effect
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(review.uid)
        assert data["state"] == Review.State.ACCEPTED
        assert "submit_time" not in data
        assert "assignment_level" in data

        review_service_unsubmit.assert_called_once_with(review)
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
        review_service_unsubmit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        review_service_unsubmit.side_effect = InvalidReviewStateError(
            "Review must be in submitted state to unsubmit."
        )
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(conference_chair)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "submitted state" in response.json()["message"]

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
        review_service_unsubmit: MagicMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        mock_visible_reviews.return_value = Review.objects.filter(pk=review.pk)
        api_client.force_login(global_admin)

        response = api_client.post(self.path(conference.name, review.uid))
        assert response.status_code == HTTPStatus.OK

        review_service_unsubmit.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        review: Review,
        review_service_unsubmit: MagicMock,
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

        review_service_unsubmit.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        review: Review,
        review_service_unsubmit: MagicMock,
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

        review_service_unsubmit.assert_called_once()

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

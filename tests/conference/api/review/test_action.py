from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Conference, Paper, Review
from app.conference.services import ReviewService
from app.conference.services.review import InvalidReviewStateError
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def review(paper: Paper, user: User) -> Review:
    return Review.objects.create(
        paper=paper,
        reviewer=user,
        state=Review.State.PENDING,
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
        assert data["state"] == Review.State.ACCEPTED

        review_service_respond.assert_called_once_with(
            review=review,
            response=Review.State.ACCEPTED,
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
        assert data["state"] == Review.State.DECLINED

        review_service_respond.assert_called_once_with(
            review=review,
            response=Review.State.DECLINED,
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

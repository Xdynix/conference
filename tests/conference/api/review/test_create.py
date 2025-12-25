from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.db import IntegrityError
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
    PaperSubmission,
    Profile,
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
from app.core.models import User
from tests.helpers import any_str


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
    )


@pytest.fixture
def reviewer(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.REVIEWER,
    )
    return user


@pytest.fixture
def review_service_assign(mocker: MockerFixture) -> AsyncMock:
    return mocker.spy(ReviewService, "assign_reviewer")


@pytest.mark.django_db(transaction=True)
class TestAssignReview:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:assign-review",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        Profile.objects.create(
            user=reviewer,
            given_name="Alice",
            family_name="Reviewer",
            affiliation="University",
        )
        Profile.objects.create(
            user=conference_chair,
            given_name="Bob",
            family_name="Chair",
            affiliation="Organization",
        )
        PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "uid": any_str,
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
                    "uid": any_str,
                    "display_name": any_str,
                },
            },
            "state": Review.State.PENDING,
            "reviewer": {
                "uid": str(reviewer.uid),
                "email": reviewer.email,
                "profile": {
                    "given_name": "Alice",
                    "family_name": "Reviewer",
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
                    "family_name": "Chair",
                    "affiliation": "Organization",
                    "region_code": "",
                },
            },
            "assignment_level": Review.AssignmentLevel.CONFERENCE,
            "contribution": "",
            "decision_reason": "",
            "comments": "",
            "confidential_remarks": "",
        }

        review_service_assign.assert_awaited_once_with(
            paper=paper,
            reviewer=reviewer,
            assigner=conference_chair,
        )

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CREATED

        review_service_assign.assert_awaited_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        TrackRoleAssignment.objects.create(
            track=track,
            user=reviewer,
            role=TrackRole.REVIEWER,
        )
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CREATED

        review_service_assign.assert_awaited_once()

    def test_global_admin_can_access(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CREATED

        review_service_assign.assert_awaited_once()

    def test_unauthenticated_returns_401(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        review_service_assign.assert_not_called()

    def test_non_admin_returns_403(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        review_service_assign.assert_not_called()

    def test_conference_not_found_returns_404(
        self,
        api_client: Client,
        conference_chair: User,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        review_service_assign.assert_not_called()

    def test_paper_not_found_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        review_service_assign.assert_not_called()

    def test_reviewer_not_found_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        review_service_assign: AsyncMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(ULID())},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "reviewer"]
        assert "User not found" in error["msg"]

        review_service_assign.assert_not_called()

    def test_reviewer_not_eligible_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        review_service_assign.side_effect = ReviewerNotEligibleError(
            "Reviewer has no eligible role in the conference."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "reviewer"]
        assert "no eligible role" in error["msg"]

    def test_assigner_not_authorized_returns_403(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        review_service_assign.side_effect = AssignerNotAuthorizedError(
            "Assigner has no admin role for this paper."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert "no admin role" in response.json()["message"]

    def test_duplicate_assignment_returns_409(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        reviewer: User,
        review_service_assign: AsyncMock,
    ) -> None:
        review_service_assign.side_effect = IntegrityError("unique constraint")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"reviewer": str(reviewer.uid)},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "already has an active review" in response.json()["message"]


@pytest.mark.django_db
class TestImportReview:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:import-review",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        Profile.objects.create(
            user=conference_chair,
            given_name="Bob",
            family_name="Chair",
            affiliation="Organization",
        )
        PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={
                "offline_reviewer_name": "External Reviewer",
                "originality": 4,
                "significance": 5,
                "technical": 3,
                "reference": 4,
                "presentation": 5,
                "match_topic": 4,
                "recommendation": 5,
                "contribution": "Good contribution",
                "decision_reason": "Accept this paper",
                "comments": "Well written",
                "confidential_remarks": "No concerns",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data == {
            "uid": any_str,
            "create_time": any_str,
            "submit_time": any_str,
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
                    "uid": any_str,
                    "display_name": any_str,
                },
            },
            "state": Review.State.SUBMITTED,
            "offline_reviewer_name": "External Reviewer",
            "assigner": {
                "uid": str(conference_chair.uid),
                "email": conference_chair.email,
                "profile": {
                    "given_name": "Bob",
                    "family_name": "Chair",
                    "affiliation": "Organization",
                    "region_code": "",
                },
            },
            "assignment_level": Review.AssignmentLevel.CONFERENCE,
            "originality": 4,
            "significance": 5,
            "technical": 3,
            "reference": 4,
            "presentation": 5,
            "match_topic": 4,
            "recommendation": 5,
            "contribution": "Good contribution",
            "decision_reason": "Accept this paper",
            "comments": "Well written",
            "confidential_remarks": "No concerns",
        }

        review = Review.objects.get(uid=data["uid"])
        assert review.reviewer is None
        assert review.state == Review.State.SUBMITTED
        assert review.submit_time is not None

    def test_empty_payload_uses_defaults(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["offline_reviewer_name"] == ""
        assert "originality" not in data
        assert data["contribution"] == ""

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_conference_admin_can_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_global_admin_can_access(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.CREATED

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_track_admin_cannot_access(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_returns_401(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_non_admin_returns_403(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found_returns_404(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found_returns_404(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_score_below_minimum_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"originality": 0},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "originality"]

    def test_score_above_maximum_returns_422(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"recommendation": 6},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "recommendation"]

    def test_upsert_existing_review_returns_200(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        existing = Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="External Reviewer",
            state=Review.State.SUBMITTED,
            originality=3,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={
                "offline_reviewer_name": "External Reviewer",
                "originality": 5,
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(existing.uid)
        assert data["originality"] == 5

        assert Review.objects.filter(paper=paper).count() == 1

    def test_upsert_updates_all_fields(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        existing = Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="External Reviewer",
            state=Review.State.SUBMITTED,
            originality=1,
            significance=1,
            contribution="Old contribution",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={
                "offline_reviewer_name": "External Reviewer",
                "originality": 5,
                "significance": 4,
                "contribution": "New contribution",
            },
        )
        assert response.status_code == HTTPStatus.OK

        existing.refresh_from_db()
        assert existing.originality == 5
        assert existing.significance == 4
        assert existing.contribution == "New contribution"

    def test_empty_name_always_creates(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="",
            state=Review.State.SUBMITTED,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"offline_reviewer_name": ""},
        )
        assert response.status_code == HTTPStatus.CREATED

        assert Review.objects.filter(paper=paper, reviewer__isnull=True).count() == 2

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
    Keyword,
    Paper,
    PaperAuthor,
    PaperFinal,
    PaperLabel,
    PaperState,
    PaperSubmission,
    Profile,
    Review,
    ReviewState,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService, ReviewService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import any_str, update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        abstract="This is the abstract",
        contribution="This is the contribution",
    )


@pytest.mark.django_db
class TestGetMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:get-my-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        keyword1 = Keyword.objects.create(text="machine learning")
        keyword2 = Keyword.objects.create(text="neural networks")
        paper.keywords.add(keyword1, keyword2)
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Alice",
            family_name="Smith",
            affiliation="University",
            region_code=Region.US.name,
            email="alice@example.com",
            ordering=0,
        )
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Bob",
            family_name="Doe",
            affiliation="Company",
            email="bob@example.com",
            phone="+1234567890",
            corresponding=True,
            ordering=1,
        )
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="final-source.zip",
            viewable_file="final-viewable.pdf",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(paper.uid),
            "conference": conference.name,
            "track": {
                "uid": str(track.uid),
                "display_name": track.display_name,
            },
            "code": paper.code,
            "state": PaperState.DRAFT,
            "title": paper.title,
            "abstract": "This is the abstract",
            "contribution": "This is the contribution",
            "keywords": ["machine learning", "neural networks"],
            "authors": [
                {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "US",
                    "email": "alice@example.com",
                    "phone": "",
                    "corresponding": False,
                },
                {
                    "given_name": "Bob",
                    "family_name": "Doe",
                    "affiliation": "Company",
                    "region_code": "",
                    "email": "bob@example.com",
                    "phone": "+1234567890",
                    "corresponding": True,
                },
            ],
            "submission": {
                "uid": str(submission.uid),
                "display_name": f"{paper.code}.pdf",
            },
            "final": {
                "uid": str(final.uid),
                "display_name": f"{paper.code}.zip",
                "viewable_display_name": f"{paper.code}-viewable.pdf",
            },
            "create_time": any_str,
        }

    def test_paper_in_invisible_track_accessible(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        update_object(track, visibility=Track.Visibility.ADMIN_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["track"]["uid"] == str(track.uid)
        assert data["track"]["display_name"] == track.display_name

    def test_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_accessible(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, visibility=Conference.Visibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_inactive(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_track_inactive(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        update_object(track, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize("state", PaperState)
    def test_visible_state_when_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state, announce_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == state

    @pytest.mark.parametrize(
        ("actual_state", "expected_state"),
        [
            # Non-decided states show actual state.
            (PaperState.DRAFT, PaperState.DRAFT),
            (PaperState.SUBMITTED, PaperState.SUBMITTED),
            (PaperState.UNDER_REVIEW, PaperState.UNDER_REVIEW),
            # Decided states masked to "Under Review".
            (PaperState.REJECTED, PaperState.UNDER_REVIEW),
            (PaperState.ACCEPTED, PaperState.UNDER_REVIEW),
            (PaperState.ACCEPTED_REVISION_NEEDED, PaperState.UNDER_REVIEW),
        ],
    )
    def test_visible_state_when_not_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        actual_state: PaperState,
        expected_state: PaperState,
    ) -> None:
        update_object(paper, state=actual_state, announce_time=None)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == expected_state

    def test_includes_empty_keywords_list(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["keywords"] == []

    def test_includes_empty_authors_list(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["authors"] == []

    def test_withdrawn_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == "Withdrawn"
        assert data["withdraw_time"] is not None

    def test_no_submission_or_final(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "submission" not in data
        assert "final" not in data

    def test_returns_latest_revision(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="old.pdf",
        )
        latest_submission = PaperSubmission.objects.create(
            paper=paper,
            revision=2,
            file="latest.pdf",
        )
        PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="old.zip",
        )
        latest_final = PaperFinal.objects.create(
            paper=paper,
            revision=2,
            source_file="latest.zip",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["submission"]["uid"] == str(latest_submission.uid)
        assert data["final"]["uid"] == str(latest_final.uid)

    def test_final_without_viewable_file(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.zip",
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert "viewable_display_name" not in data["final"]


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    mock = mocker.patch.object(ReviewService, "visible_reviews")
    mock.return_value = Review.objects.none()
    return mock


@pytest.mark.django_db
class TestGetPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:get-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        update_object(conference_chair, email="admin@example.com")
        Profile.objects.create(
            user=conference_chair,
            given_name="Admin",
            family_name="User",
            affiliation="Organization",
            region_code=Region.US.name,
        )
        update_object(paper, owner=conference_chair)
        keyword1 = Keyword.objects.create(text="machine learning")
        keyword2 = Keyword.objects.create(text="neural networks")
        paper.keywords.add(keyword1, keyword2)
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Alice",
            family_name="Smith",
            affiliation="University",
            email="alice@example.com",
            ordering=0,
        )
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="submission.pdf",
        )
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="final-source.zip",
            viewable_file="final-viewable.pdf",
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(paper.uid),
            "conference": conference.name,
            "track": {
                "uid": str(track.uid),
                "display_name": track.display_name,
            },
            "code": paper.code,
            "create_time": any_str,
            "state": PaperState.DRAFT,
            "visible_state": PaperState.DRAFT,
            "owner": {
                "uid": str(conference_chair.uid),
                "email": "admin@example.com",
                "profile": {
                    "given_name": "Admin",
                    "family_name": "User",
                    "affiliation": "Organization",
                    "region_code": "US",
                },
            },
            "title": paper.title,
            "abstract": "This is the abstract",
            "contribution": "This is the contribution",
            "keywords": ["machine learning", "neural networks"],
            "authors": [
                {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "",
                    "email": "alice@example.com",
                    "phone": "",
                    "corresponding": False,
                },
            ],
            "submission": {
                "uid": str(submission.uid),
                "display_name": f"{paper.code}.pdf",
            },
            "final": {
                "uid": str(final.uid),
                "display_name": f"{paper.code}.zip",
                "viewable_display_name": f"{paper.code}-viewable.pdf",
            },
            "review_stat": {
                "pending_count": 0,
                "declined_count": 0,
                "accepted_count": 0,
                "submitted_count": 0,
                "cancelled_count": 0,
            },
            "recommendation_summary": {},
            "labels": {},
        }

        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)
        mock_visible_reviews.assert_awaited_once_with(
            conference=conference,
            user=conference_chair,
        )

    def test_withdrawn_paper(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["visible_state"] == "Withdrawn"
        assert data["withdraw_time"] is not None

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

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_state_not_masked_for_admin(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        update_object(paper, state=PaperState.REJECTED, announce_time=None)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == PaperState.REJECTED
        assert data["visible_state"] == PaperState.UNDER_REVIEW

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
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
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
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
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
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
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

    def test_review_stat_counts_visible_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        Review.objects.create(paper=paper, state=ReviewState.PENDING)
        Review.objects.create(paper=paper, state=ReviewState.ACCEPTED)
        Review.objects.create(paper=paper, state=ReviewState.SUBMITTED)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.filter(paper=paper)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["review_stat"] == {
            "pending_count": 1,
            "declined_count": 0,
            "accepted_count": 1,
            "submitted_count": 1,
            "cancelled_count": 0,
        }

    def test_review_stat_counts_all_states(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        for state in ReviewState:
            Review.objects.create(paper=paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.filter(paper=paper)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["review_stat"] == {
            "pending_count": 1,
            "declined_count": 1,
            "accepted_count": 1,
            "submitted_count": 1,
            "cancelled_count": 1,
        }

    def test_review_stat_only_counts_visible_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        visible_review = Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
        )
        Review.objects.create(paper=paper, state=ReviewState.PENDING)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        mock_visible_reviews.return_value = Review.objects.filter(pk=visible_review.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["review_stat"] == {
            "pending_count": 0,
            "declined_count": 0,
            "accepted_count": 0,
            "submitted_count": 1,
            "cancelled_count": 0,
        }

    def test_recommendation_summary_no_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["recommendation_summary"] == {}

    def test_recommendation_summary_submitted_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=4,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=5,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["recommendation_summary"] == {
            "submitted_average": 4.5,
            "submitted_and_draft_average": 4.5,
        }

    def test_recommendation_summary_includes_draft_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=4,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.ACCEPTED,
            recommendation=2,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["recommendation_summary"] == {
            "submitted_average": 4.0,
            "submitted_and_draft_average": 3.0,
        }

    def test_recommendation_summary_excludes_null_recommendations(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=4,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=None,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["recommendation_summary"] == {
            "submitted_average": 4.0,
            "submitted_and_draft_average": 4.0,
        }

    def test_recommendation_summary_excludes_other_states(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        Review.objects.create(
            paper=paper,
            state=ReviewState.SUBMITTED,
            recommendation=5,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.PENDING,
            recommendation=1,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.DECLINED,
            recommendation=1,
        )
        Review.objects.create(
            paper=paper,
            state=ReviewState.CANCELLED,
            recommendation=1,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["recommendation_summary"] == {
            "submitted_average": 5.0,
            "submitted_and_draft_average": 5.0,
        }

    def test_labels_serialized(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        PaperLabel.objects.create(paper=paper, key="env", value="prod")
        PaperLabel.objects.create(paper=paper, key="tier", value="frontend")
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["labels"] == {"env": "prod", "tier": "frontend"}

    def test_labels_empty_when_no_labels(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["labels"] == {}

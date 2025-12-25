from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    Paper,
    Profile,
    Review,
    Track,
    TrackRole,
    TrackRoleAssignment,
    UserConferenceProfile,
)
from app.conference.services import PaperService
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture(autouse=True)
def mock_visible_papers(mocker: MockerFixture, paper: Paper) -> AsyncMock:
    mock = mocker.patch.object(PaperService, "visible_papers")
    mock.return_value = Paper.objects.filter(pk=paper.pk)
    return mock


@pytest.mark.django_db
class TestListReviewerCandidates:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:list-reviewer-candidates",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        reviewer = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(
            user=reviewer,
            given_name="Alice",
            family_name="Reviewer",
            affiliation="University",
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=reviewer,
            role=ConferenceRole.REVIEWER,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(reviewer.uid),
                "email": reviewer.email,
                "profile": {
                    "given_name": "Alice",
                    "family_name": "Reviewer",
                    "affiliation": "University",
                    "region_code": "",
                },
                "workload": {
                    "pending_count": 0,
                    "accepted_count": 0,
                    "submitted_count": 0,
                    "desired_count": 0,
                },
                "has_declined": False,
                "match_score": 0,
            }
        ]

    def test_excludes_paper_owner(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=paper.owner,
            role=ConferenceRole.REVIEWER,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = [c["uid"] for c in data]
        assert str(paper.owner.uid) not in uids

    def test_excludes_requester(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = [c["uid"] for c in data]
        assert str(conference_chair.uid) not in uids

    def test_excludes_users_with_active_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=conference_reviewer,
            state=Review.State.PENDING,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = [c["uid"] for c in data]
        assert str(conference_reviewer.uid) not in uids

    def test_includes_users_with_declined_reviews(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=conference_reviewer,
            state=Review.State.DECLINED,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = [c["uid"] for c in data]
        assert str(conference_reviewer.uid) in uids

        candidate = next(c for c in data if c["uid"] == str(conference_reviewer.uid))
        assert candidate["has_declined"] is True

    def test_workload_counts(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_reviewer: User,
        track: Track,
        paper: Paper,
    ) -> None:
        other_paper1 = Paper.objects.create(
            conference=conference,
            track=track,
            owner=conference_chair,
            code="P2",
        )
        other_paper2 = Paper.objects.create(
            conference=conference,
            track=track,
            owner=conference_chair,
            code="P3",
        )
        other_paper3 = Paper.objects.create(
            conference=conference,
            track=track,
            owner=conference_chair,
            code="P4",
        )
        Review.objects.create(
            paper=other_paper1,
            reviewer=conference_reviewer,
            state=Review.State.PENDING,
        )
        Review.objects.create(
            paper=other_paper2,
            reviewer=conference_reviewer,
            state=Review.State.ACCEPTED,
        )
        Review.objects.create(
            paper=other_paper3,
            reviewer=conference_reviewer,
            state=Review.State.SUBMITTED,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        candidate = next(c for c in data if c["uid"] == str(conference_reviewer.uid))
        assert candidate["workload"] == {
            "pending_count": 1,
            "accepted_count": 1,
            "submitted_count": 1,
            "desired_count": 0,
        }

    def test_desired_count_from_profile(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        UserConferenceProfile.objects.create(
            user=conference_reviewer,
            conference=conference,
            desired_paper_count=10,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        candidate = next(c for c in data if c["uid"] == str(conference_reviewer.uid))
        assert candidate["workload"]["desired_count"] == 10

    def test_match_score_keyword_overlap(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        kw1 = Keyword.objects.create(text="machine-learning")
        kw2 = Keyword.objects.create(text="deep-learning")
        kw3 = Keyword.objects.create(text="nlp")
        paper.keywords.add(kw1, kw2)
        profile = UserConferenceProfile.objects.create(
            user=conference_reviewer,
            conference=conference,
        )
        profile.interested_keywords.add(kw1, kw3)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        candidate = next(c for c in data if c["uid"] == str(conference_reviewer.uid))
        assert candidate["match_score"] == 1

    def test_conference_admin_sees_all_eligible_users(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        track: Track,
        paper: Paper,
    ) -> None:
        conf_reviewer = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=conf_reviewer,
            role=ConferenceRole.REVIEWER,
        )
        track_reviewer = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_reviewer,
            role=TrackRole.REVIEWER,
        )
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=GlobalRole.ADMIN)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = {c["uid"] for c in data}
        assert str(conf_reviewer.uid) in uids
        assert str(track_reviewer.uid) in uids
        assert str(admin.uid) in uids

    def test_track_admin_sees_only_track_reviewers(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        conf_reviewer = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=conf_reviewer,
            role=ConferenceRole.REVIEWER,
        )
        track_reviewer = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_reviewer,
            role=TrackRole.REVIEWER,
        )
        api_client.force_login(track_admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        uids = {c["uid"] for c in data}
        assert str(track_reviewer.uid) in uids
        assert str(conf_reviewer.uid) not in uids

    def test_returns_empty_list_when_no_candidates(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
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

    def test_authorization_global_admin(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
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
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
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

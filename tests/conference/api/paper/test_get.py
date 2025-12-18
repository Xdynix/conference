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
    PaperSubmission,
    Profile,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import any_str, update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=Conference.Visibility.PUBLIC,
    )


@pytest.fixture
def track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


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
            "state": Paper.State.DRAFT,
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

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize("state", Paper.State)
    def test_visible_state_when_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        state: Paper.State,
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
            (Paper.State.DRAFT, Paper.State.DRAFT),
            (Paper.State.SUBMITTED, Paper.State.SUBMITTED),
            (Paper.State.UNDER_REVIEW, Paper.State.UNDER_REVIEW),
            # Decided states masked to "Under Review".
            (Paper.State.REJECTED, Paper.State.UNDER_REVIEW),
            (Paper.State.ACCEPTED, Paper.State.UNDER_REVIEW),
            (Paper.State.ACCEPTED_REVISION_NEEDED, Paper.State.UNDER_REVIEW),
        ],
    )
    def test_visible_state_when_not_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        actual_state: Paper.State,
        expected_state: Paper.State,
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
def conference_admin(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


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
        conference_admin: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        update_object(conference_admin, email="admin@example.com")
        Profile.objects.create(
            user=conference_admin,
            given_name="Admin",
            family_name="User",
            affiliation="Organization",
            region_code=Region.US.name,
        )
        update_object(paper, owner=conference_admin)
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
        api_client.force_login(conference_admin)

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
            "state": Paper.State.DRAFT,
            "visible_state": Paper.State.DRAFT,
            "owner": {
                "uid": str(conference_admin.uid),
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
            "create_time": any_str,
        }

        mock_visible_papers.assert_awaited_once_with(conference, conference_admin)

    def test_withdrawn_paper(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        paper: Paper,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["visible_state"] == "Withdrawn"
        assert data["withdraw_time"] is not None

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=-1)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_admin: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.get(self.path("nonexistent-conference", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_state_not_masked_for_admin(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        paper: Paper,
        mock_visible_papers: AsyncMock,
    ) -> None:
        update_object(paper, state=Paper.State.REJECTED, announce_time=None)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["state"] == Paper.State.REJECTED
        assert data["visible_state"] == Paper.State.UNDER_REVIEW

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

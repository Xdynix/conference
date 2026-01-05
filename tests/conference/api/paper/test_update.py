from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

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
    ConferenceVisibility,
    Keyword,
    Paper,
    PaperAuthor,
    PaperState,
    Profile,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import KeywordService, PaperService
from app.conference.services.paper import PaperStateError, PaperWithdrawnError
from app.core.models import User
from app.utils.enums import Region
from tests.helpers import any_str, update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Original Title",
        abstract="Original abstract",
        contribution="Original contribution",
    )


@pytest.fixture
def paper_service_update(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "update_paper")


@pytest.mark.django_db
class TestUpdateMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:update-my-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        keyword_ai = Keyword.objects.create(text="AI")
        keyword_ml = Keyword.objects.create(text="ML")
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Existing",
            family_name="Author",
            ordering=0,
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={
                "title": "Updated Title",
                "abstract": "Updated abstract",
                "contribution": "Updated contribution",
                "keywords": ["AI", "ML"],
                "authors": [
                    {
                        "given_name": "Alice",
                        "family_name": "Smith",
                        "affiliation": "University",
                        "region_code": "US",
                        "email": "alice@example.com",
                        "phone": "+1234567890",
                        "corresponding": True,
                    },
                    {
                        "given_name": "Bob",
                        "family_name": "Doe",
                        "affiliation": "Company",
                        "email": "bob@example.com",
                    },
                ],
            },
        )
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
            "title": "Updated Title",
            "abstract": "Updated abstract",
            "contribution": "Updated contribution",
            "keywords": ["AI", "ML"],
            "authors": [
                {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "US",
                    "email": "alice@example.com",
                    "phone": "+1234567890",
                    "corresponding": True,
                },
                {
                    "given_name": "Bob",
                    "family_name": "Doe",
                    "affiliation": "Company",
                    "region_code": "",
                    "email": "bob@example.com",
                    "phone": "",
                    "corresponding": False,
                },
            ],
            "final_revision_remaining": 1,
            "create_time": any_str,
        }

        paper_service_update.assert_called_once_with(
            paper=paper,
            mode="author",
            title="Updated Title",
            abstract="Updated abstract",
            contribution="Updated contribution",
            keywords=[keyword_ai, keyword_ml],
            authors=[
                {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "US",
                    "email": "alice@example.com",
                    "phone": "+1234567890",
                    "corresponding": True,
                },
                {
                    "given_name": "Bob",
                    "family_name": "Doe",
                    "affiliation": "Company",
                    "email": "bob@example.com",
                },
            ],
        )

    def test_trims_whitespace_fields(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        Keyword.objects.create(text="AI")
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={
                "title": "  Updated Title  ",
                "abstract": "  Updated abstract  ",
                "contribution": "  Updated contribution  ",
                "keywords": ["  AI  "],
                "authors": [
                    {
                        "given_name": "  Alice  ",
                        "family_name": "  Smith  ",
                        "affiliation": "  University  ",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["abstract"] == "  Updated abstract"
        assert data["contribution"] == "  Updated contribution"
        assert data["keywords"] == ["AI"]
        assert data["authors"][0]["given_name"] == "Alice"
        assert data["authors"][0]["family_name"] == "Smith"
        assert data["authors"][0]["affiliation"] == "University"

        paper_service_update.assert_called_once()
        call_kwargs = paper_service_update.call_args.kwargs
        assert call_kwargs["mode"] == "author"
        assert call_kwargs["title"] == "Updated Title"
        assert call_kwargs["abstract"] == "  Updated abstract"
        assert call_kwargs["contribution"] == "  Updated contribution"

    def test_partial_update_keeps_existing_values(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"abstract": "Revised abstract"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["title"] == "Original Title"
        assert data["abstract"] == "Revised abstract"
        assert data["contribution"] == "Original contribution"
        assert data["keywords"] == []
        assert data["authors"] == []

        call_kwargs = paper_service_update.call_args.kwargs
        assert call_kwargs["paper"] == paper
        assert call_kwargs["mode"] == "author"
        assert call_kwargs["title"] is None
        assert call_kwargs["abstract"] == "Revised abstract"
        assert call_kwargs["contribution"] is None
        assert call_kwargs["keywords"] is None
        assert call_kwargs["authors"] is None

    def test_rejects_non_draft_state(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        paper_service_update.side_effect = PaperStateError(
            "Paper must be in Draft state to update."
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Should fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Paper must be in Draft state to update."

        paper_service_update.assert_called_once()

    def test_rejects_withdrawn_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        paper_service_update.side_effect = PaperWithdrawnError("Withdrawn paper")
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Should fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Withdrawn paper"

        paper_service_update.assert_called_once()

    def test_unknown_keywords(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: nonexistent."),
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"keywords": ["Unknown"]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body", "payload", "keywords"]
        assert "Unknown keywords" in error["msg"]

        paper_service_update.assert_not_called()

    def test_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, "NONEXISTENT"),
            data={"title": "No Found"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_owned_by_another_user(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        user: User,
        paper: Paper,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        update_object(paper, owner=other_user)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "No access"},
        )
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Deleted"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path("nonexistent-conference", "PAPER-001"),
            data={"title": "No conference"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(conference, visibility=ConferenceVisibility.MEMBER_ONLY)
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Inactive"},
        )
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Inactive"},
        )
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Inactive"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Unauthorized"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.mark.django_db
class TestUpdatePaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:update-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper: Paper,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        keyword_ai = Keyword.objects.create(text="AI")
        keyword_ml = Keyword.objects.create(text="ML")
        update_object(conference_chair, email="admin@example.com")
        Profile.objects.create(
            user=conference_chair,
            given_name="Admin",
            family_name="User",
            affiliation="Organization",
            region_code=Region.US.name,
        )
        update_object(paper, owner=conference_chair)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={
                "title": "Admin Updated",
                "keywords": ["AI", "ML"],
            },
        )
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
            "title": "Admin Updated",
            "abstract": "Original abstract",
            "contribution": "Original contribution",
            "keywords": ["AI", "ML"],
            "authors": [],
            "final_revision_limit": 1,
            "final_revision_remaining": 1,
            "review_stat": {
                "pending_count": 0,
                "declined_count": 0,
                "accepted_count": 0,
                "submitted_count": 0,
                "cancelled_count": 0,
            },
            "recommendation_summary": {},
            "labels": {},
            "has_ieee_ecopyright_consent": False,
        }

        paper_service_update.assert_called_once_with(
            paper=paper,
            mode="admin",
            title="Admin Updated",
            abstract=None,
            contribution=None,
            keywords=[keyword_ai, keyword_ml],
            authors=None,
        )
        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)

    def test_trims_whitespace_fields(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        Keyword.objects.create(text="AI")
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={
                "title": "  Admin Updated  ",
                "abstract": "  Admin abstract  ",
                "contribution": "  Admin contribution  ",
                "keywords": ["  AI  "],
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["title"] == "Admin Updated"
        assert data["abstract"] == "  Admin abstract"
        assert data["contribution"] == "  Admin contribution"
        assert data["keywords"] == ["AI"]

        paper_service_update.assert_called_once()
        call_kwargs = paper_service_update.call_args.kwargs
        assert call_kwargs["mode"] == "admin"
        assert call_kwargs["title"] == "Admin Updated"
        assert call_kwargs["abstract"] == "  Admin abstract"
        assert call_kwargs["contribution"] == "  Admin contribution"

    def test_rejects_withdrawn_paper(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_service_update.side_effect = PaperWithdrawnError("Withdrawn paper")
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Should fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Withdrawn paper"

        paper_service_update.assert_called_once()

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, "NONEXISTENT"),
            data={"title": "No Found"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path("nonexistent-conference", "PAPER-001"),
            data={"title": "No Found"},
        )
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Inactive"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.parametrize(
        "state",
        [state for state in PaperState if state not in PaperState.decided()],
    )
    def test_track_admin_can_update_non_decided(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
        state: PaperState,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(paper, state=state)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(track_admin)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"contribution": "Track admin edit"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once_with(
            paper=paper,
            mode="track_admin",
            title=None,
            abstract=None,
            contribution="Track admin edit",
            keywords=None,
            authors=None,
        )
        mock_visible_papers.assert_awaited_once_with(conference, track_admin)

    def test_track_admin_cannot_update_decided_paper(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        paper_service_update.side_effect = PaperStateError(
            "Only conference admins can update papers after decision."
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(track_admin)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Should fail"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert (
            response.json()["message"]
            == "Only conference admins can update papers after decision."
        )

        paper_service_update.assert_called_once()
        mock_visible_papers.assert_awaited_once_with(conference, track_admin)

    def test_global_admin_can_update_decided(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        global_admin: User,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"contribution": "Global update"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once_with(
            paper=paper,
            mode="admin",
            title=None,
            abstract=None,
            contribution="Global update",
            keywords=None,
            authors=None,
        )
        mock_visible_papers.assert_awaited_once_with(conference, global_admin)

    def test_conference_admin_can_update_decided(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_chair: User,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Decided update"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once_with(
            paper=paper,
            mode="admin",
            title="Decided update",
            abstract=None,
            contribution=None,
            keywords=None,
            authors=None,
        )
        mock_visible_papers.assert_awaited_once_with(conference, conference_chair)

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "No auth"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_service_update: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, "PAPER-001"),
            data={"title": "Forbidden"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_update.assert_not_called()

    def test_authorization_global_admin(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
        paper_service_update: MagicMock,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Allowed"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        paper_service_update: MagicMock,
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Allowed"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        mock_visible_papers: AsyncMock,
        paper_service_update: MagicMock,
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

        response = api_client.patch(
            self.path(conference.name, paper.code),
            data={"title": "Allowed"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_update.assert_called_once()

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
            self.path(conference.name, "PAPER-001"),
            data={"title": "Forbidden"},
        )
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

        response = api_client.patch(
            self.path(conference.name, "PAPER-001"),
            data={"title": "Forbidden"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

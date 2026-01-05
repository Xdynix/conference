from datetime import datetime
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
    ConferenceVisibility,
    IEEEeCopyrightConsent,
    Paper,
    PaperAuthor,
    PaperFinal,
    PaperState,
    PaperSubmission,
    Profile,
    Review,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
)
from app.conference.services import PaperService, ReviewService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import any_str, update_object


def create_paper(
    conference: Conference,
    track: Track,
    owner: User,
    *,
    code: str = "PAPER-001",
    state: PaperState = PaperState.DRAFT,
    title: str = "Test Paper",
    announce_time: datetime | None = None,
    delete_time: datetime | None = None,
) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=owner,
        code=code,
        state=state,
        title=title,
        announce_time=announce_time,
        delete_time=delete_time,
    )


@pytest.mark.django_db
class TestListMyPapers:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-my-papers", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = create_paper(conference, track, user)
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Bob",
            family_name="Doe",
            affiliation="Company",
            region_code=Region.GB.name,
            email="bob@example.com",
            corresponding=True,
            ordering=1,
        )
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
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "uid": str(paper.uid),
                    "conference": conference.name,
                    "track": {
                        "uid": str(track.uid),
                        "display_name": track.display_name,
                    },
                    "code": paper.code,
                    "create_time": any_str,
                    "state": PaperState.DRAFT,
                    "title": paper.title,
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
                        {
                            "given_name": "Bob",
                            "family_name": "Doe",
                            "affiliation": "Company",
                            "region_code": "GB",
                            "email": "bob@example.com",
                            "phone": "",
                            "corresponding": True,
                        },
                    ],
                    "final_revision_remaining": 0,
                    "submission": {
                        "uid": str(submission.uid),
                        "display_name": f"{paper.code}.pdf",
                        "download_url": any_str,
                    },
                    "final": {
                        "uid": str(final.uid),
                        "display_name": f"{paper.code}.zip",
                        "viewable_display_name": f"{paper.code}-viewable.pdf",
                        "download_url": any_str,
                        "viewable_download_url": any_str,
                    },
                },
            ],
        }

    def test_papers_in_invisible_track_included(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        update_object(track, visibility=TrackVisibility.ADMIN_ONLY)
        paper = create_paper(conference, track, user)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["code"] == paper.code
        assert paper_data["track"]["uid"] == str(track.uid)
        assert paper_data["track"]["display_name"] == track.display_name

    def test_returns_only_papers_owned_by_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        user_paper = create_paper(conference, track, user, code="USER-001")
        create_paper(conference, track, other_user, code="OTHER-001")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["code"] == user_paper.code

    def test_scoped_to_conference(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        paper_in_conference = create_paper(conference, track, user, code="CONF-001")
        create_paper(other_conference, other_track, user, code="OTHER-CONF-001")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["code"] == paper_in_conference.code

    def test_withdrawn_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = create_paper(conference, track, user, code="CONF-001")
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["state"] == "Withdrawn"
        assert paper_data["withdraw_time"] is not None

    def test_excludes_deleted_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        active_paper = create_paper(conference, track, user, code="ACTIVE-001")
        create_paper(
            conference,
            track,
            user,
            code="DELETED-001",
            delete_time=timezone.now(),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["code"] == active_paper.code

    def test_returns_empty_list_when_no_papers(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"items": []}

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_visible_to_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        hidden_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.MEMBER_ONLY,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(hidden_conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_inactive(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_track_inactive(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        update_object(track, active=False)
        create_paper(conference, track, user, code="PAPER-001")
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"items": []}

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize("state", PaperState.decided())
    def test_visible_state_when_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        state: PaperState,
    ) -> None:
        create_paper(
            conference,
            track,
            user,
            state=state,
            announce_time=timezone.now(),
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["state"] == state

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
        track: Track,
        actual_state: PaperState,
        expected_state: PaperState,
    ) -> None:
        create_paper(
            conference,
            track,
            user,
            state=actual_state,
            announce_time=None,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["state"] == expected_state


@pytest.fixture
def mock_visible_papers(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(PaperService, "visible_papers")


@pytest.fixture
def mock_visible_reviews(mocker: MockerFixture) -> AsyncMock:
    mock = mocker.patch.object(ReviewService, "visible_reviews")
    mock.return_value = Review.objects.none()
    return mock


@pytest.mark.django_db
class TestListPapers:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-papers", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,
    ) -> None:
        update_object(conference_chair, email="admin@example.com")
        Profile.objects.create(
            user=conference_chair,
            given_name="Bob",
            family_name="Doe",
            affiliation="Organization",
            region_code=Region.CN.name,
        )
        paper = create_paper(
            conference,
            track,
            conference_chair,
            state=PaperState.ACCEPTED,
        )
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

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "items": [
                {
                    "uid": str(paper.uid),
                    "conference": conference.name,
                    "track": {
                        "uid": str(track.uid),
                        "display_name": track.display_name,
                    },
                    "code": paper.code,
                    "create_time": any_str,
                    "state": PaperState.ACCEPTED,
                    "visible_state": PaperState.UNDER_REVIEW,
                    "owner": {
                        "uid": str(conference_chair.uid),
                        "email": "admin@example.com",
                        "profile": {
                            "given_name": "Bob",
                            "family_name": "Doe",
                            "affiliation": "Organization",
                            "region_code": "CN",
                        },
                    },
                    "title": paper.title,
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
                    "final_revision_limit": 1,
                    "final_revision_remaining": 0,
                    "submission": {
                        "uid": str(submission.uid),
                        "display_name": f"{paper.code}.pdf",
                        "download_url": any_str,
                    },
                    "final": {
                        "uid": str(final.uid),
                        "display_name": f"{paper.code}.zip",
                        "viewable_display_name": f"{paper.code}-viewable.pdf",
                        "download_url": any_str,
                        "viewable_download_url": any_str,
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
                    "has_ieee_ecopyright_consent": False,
                },
            ],
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
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper = create_paper(conference, track, conference_chair, code="CONF-001")
        update_object(paper, withdraw_time=timezone.now())
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["visible_state"] == "Withdrawn"
        assert paper_data["withdraw_time"] is not None

    def test_returns_empty_list_when_no_papers(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        mock_visible_papers.return_value = Paper.objects.filter(pk=-1)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {"items": []}

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        faker: Faker,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        inactive_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            active=False,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(inactive_conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_state_not_masked_for_admin(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper = create_paper(
            conference,
            track,
            conference_chair,
            state=PaperState.REJECTED,
            announce_time=None,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [paper_data] = data["items"]
        assert paper_data["state"] == PaperState.REJECTED
        assert paper_data["visible_state"] == PaperState.UNDER_REVIEW

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        mock_visible_papers: AsyncMock,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        mock_visible_papers.return_value = Paper.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        mock_visible_papers: AsyncMock,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        mock_visible_papers: AsyncMock,
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        mock_visible_papers.return_value = Paper.objects.filter(pk=-1)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
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

        response = api_client.get(self.path(conference.name))
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

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_state_filter(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_draft = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-DRAFT",
            state=PaperState.DRAFT,
        )
        paper_submitted = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-SUBMITTED",
            state=PaperState.SUBMITTED,
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_draft.pk, paper_submitted.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"state": PaperState.SUBMITTED},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-SUBMITTED"

    def test_announced_filter_true(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_announced = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-ANNOUNCED",
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        paper_not_announced = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-NOT-ANNOUNCED",
            announce_time=None,
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_announced.pk, paper_not_announced.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"announced": "true"},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-ANNOUNCED"

    def test_announced_filter_false(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_announced = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-ANNOUNCED",
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        paper_not_announced = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-NOT-ANNOUNCED",
            announce_time=None,
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_announced.pk, paper_not_announced.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"announced": "false"},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-NOT-ANNOUNCED"

    def test_withdrawn_filter_true(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_withdrawn = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-WITHDRAWN",
        )
        update_object(paper_withdrawn, withdraw_time=timezone.now())
        paper_active = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-ACTIVE",
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_withdrawn.pk, paper_active.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"withdrawn": "true"},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-WITHDRAWN"

    def test_withdrawn_filter_false(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_withdrawn = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-WITHDRAWN",
        )
        update_object(paper_withdrawn, withdraw_time=timezone.now())
        paper_active = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-ACTIVE",
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_withdrawn.pk, paper_active.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"withdrawn": "false"},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-ACTIVE"

    def test_label_selector_filter(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
    ) -> None:
        paper_prod = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-PROD",
        )
        paper_prod.labels.create(key="env", value="prod")
        paper_staging = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-STAGING",
        )
        paper_staging.labels.create(key="env", value="staging")
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_prod.pk, paper_staging.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"label_selector": "env=prod"},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == "PAPER-PROD"

    @pytest.mark.parametrize(
        ("search_term", "expected_code"),
        [
            ("Machine Learning", "PAPER-ML"),
            ("PAPER-ML", "PAPER-ML"),
            ("owner@example.com", "PAPER-ML"),
            ("author@example.com", "PAPER-ML"),
        ],
    )
    def test_search_filter(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
        search_term: str,
        expected_code: str,
    ) -> None:
        update_object(conference_chair, email="owner@example.com")
        paper_ml = create_paper(
            conference,
            track,
            conference_chair,
            code="PAPER-ML",
            title="Machine Learning Advances",
        )
        PaperAuthor.objects.create(
            paper=paper_ml,
            given_name="Alice",
            family_name="Smith",
            affiliation="University",
            email="author@example.com",
            ordering=0,
        )
        other_user = User.objects.create_user(username=faker.user_name())
        paper_other = create_paper(
            conference,
            track,
            other_user,
            code="PAPER-OTHER",
            title="Unrelated Topic",
        )
        mock_visible_papers.return_value = Paper.objects.filter(
            pk__in=[paper_ml.pk, paper_other.pk]
        )
        api_client.force_login(conference_chair)

        response = api_client.get(
            self.path(conference.name),
            {"search": search_term},
        )
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()["items"]
        assert data["code"] == expected_code

    def test_has_ieee_ecopyright_consent_true_when_consent_exists(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_papers: AsyncMock,
        mock_visible_reviews: AsyncMock,  # noqa: ARG002
    ) -> None:
        paper = create_paper(conference, track, conference_chair)
        IEEEeCopyrightConsent.objects.create(paper=paper)
        mock_visible_papers.return_value = Paper.objects.filter(pk=paper.pk)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        assert response.status_code == HTTPStatus.OK
        [data] = response.json()["items"]
        assert data["has_ieee_ecopyright_consent"] is True

from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    CodePool,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Keyword,
    Paper,
    PaperState,
    Profile,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
)
from app.conference.services import ClaimService, KeywordService, PaperService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import any_str, approx_now, update_object


@pytest.fixture
def code_pool(conference: Conference) -> CodePool:
    return CodePool.objects.create(
        conference=conference,
        name="Main Pool",
        prefix="TEST-",
    )


@pytest.fixture
def track(faker: Faker, conference: Conference, code_pool: CodePool) -> Track:
    return Track.objects.create(
        conference=conference,
        code_pool=code_pool,
        display_name=faker.word(),
        visibility=TrackVisibility.PUBLIC,
        submissions_enabled=True,
    )


@pytest.fixture
def paper_service_create(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "create_paper")


@pytest.mark.django_db
class TestCreateDraft:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-draft", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        kw1 = Keyword.objects.create(text="Machine Learning")
        kw2 = Keyword.objects.create(text="Neural Networks")
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper Title",
                "abstract": "This is the abstract.",
                "contribution": "This is the contribution.",
                "keywords": [kw1.text, kw2.text],
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
                        "family_name": "Jones",
                        "affiliation": "Institute",
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "uid": any_str,
            "conference": conference.name,
            "track": {
                "uid": str(track.uid),
                "display_name": track.display_name,
            },
            "code": "TEST-001",
            "title": "Test Paper Title",
            "abstract": "This is the abstract.",
            "contribution": "This is the contribution.",
            "state": PaperState.DRAFT,
            "keywords": ["Machine Learning", "Neural Networks"],
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
                    "family_name": "Jones",
                    "affiliation": "Institute",
                    "region_code": "",
                    "email": "",
                    "phone": "",
                    "corresponding": False,
                },
            ],
            "final_revision_remaining": 1,
            "create_time": approx_now(),
        }

        paper_service_create.assert_called_once()
        call_kwargs = paper_service_create.call_args.kwargs
        assert call_kwargs["track"] == track
        assert call_kwargs["owner"] == user
        assert call_kwargs["title"] == "Test Paper Title"

    def test_minimal_payload(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Minimal Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["title"] == "Minimal Paper"
        assert data["abstract"] == ""
        assert data["contribution"] == ""
        assert data["keywords"] == []
        assert data["authors"] == []

        paper_service_create.assert_called_once()
        call_kwargs = paper_service_create.call_args.kwargs
        assert call_kwargs["abstract"] == ""
        assert call_kwargs["contribution"] == ""
        assert list(call_kwargs["keywords"]) == []
        assert list(call_kwargs["authors"]) == []

    def test_trims_whitespace(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "  Trimmed Title  ",
                "abstract": "  Formatted\nAbstract  ",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["title"] == "Trimmed Title"
        assert data["abstract"] == "  Formatted\nAbstract"

    def test_invalid_track_uid(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(ULID()),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert "Invalid track UID" in error["msg"]

        paper_service_create.assert_not_called()

    def test_track_not_visible_to_user(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        conference: Conference,
        code_pool: CodePool,
        paper_service_create: MagicMock,
    ) -> None:
        hidden_track = Track.objects.create(
            conference=conference,
            code_pool=code_pool,
            display_name=faker.word(),
            visibility=TrackVisibility.ADMIN_ONLY,
            submissions_enabled=True,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(hidden_track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]

        paper_service_create.assert_not_called()

    def test_track_not_accepting_submissions(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        update_object(track, submissions_enabled=False)
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert "not currently accepting submissions" in error["msg"]

        paper_service_create.assert_not_called()

    def test_track_no_code_pool(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        update_object(track, code_pool=None)
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert "not configured for paper submissions" in error["msg"]

        paper_service_create.assert_called_once()

    def test_unknown_keywords(
        self,
        mocker: MockerFixture,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: nonexistent."),
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
                "keywords": ["nonexistent"],
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "keywords"]
        assert "Unknown keywords" in error["msg"]

        paper_service_create.assert_not_called()

    def test_missing_title(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"track": str(track.uid)},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "title"]

        paper_service_create.assert_not_called()

    def test_empty_title(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "title"]

        paper_service_create.assert_not_called()

    def test_conference_not_found(
        self,
        api_client: Client,
        user: User,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path("nonexistent-conference"),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        paper_service_create.assert_not_called()

    def test_conference_not_visible(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
        paper_service_create: MagicMock,
    ) -> None:
        hidden_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.ADMIN_ONLY,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(hidden_conference.name),
            data={
                "track": str(ULID()),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        paper_service_create.assert_not_called()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        paper_service_create.assert_not_called()


@pytest.mark.django_db
class TestCreatePaper:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-paper", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper_service_create: MagicMock,
    ) -> None:
        update_object(conference_chair, email="admin@example.com")
        Profile.objects.create(
            user=conference_chair,
            given_name="Admin",
            family_name="User",
            affiliation="Organization",
            region_code=Region.US.name,
        )
        kw1 = Keyword.objects.create(text="Machine Learning")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Admin Created Paper",
                "abstract": "Abstract text.",
                "contribution": "Contribution text.",
                "keywords": [kw1.text],
                "authors": [
                    {
                        "given_name": "Alice",
                        "family_name": "Smith",
                        "affiliation": "University",
                        "email": "alice@example.com",
                        "corresponding": True,
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "uid": any_str,
            "conference": conference.name,
            "track": {
                "uid": str(track.uid),
                "display_name": track.display_name,
            },
            "code": "TEST-001",
            "create_time": approx_now(),
            "title": "Admin Created Paper",
            "abstract": "Abstract text.",
            "contribution": "Contribution text.",
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
            "keywords": ["Machine Learning"],
            "authors": [
                {
                    "given_name": "Alice",
                    "family_name": "Smith",
                    "affiliation": "University",
                    "region_code": "",
                    "email": "alice@example.com",
                    "phone": "",
                    "corresponding": True,
                },
            ],
            "final_revision_limit": 1,
            "final_revision_remaining": 1,
            "review_stat": {
                "pending_count": 0,
                "declined_count": 0,
                "accepted_count": 0,
                "submitted_count": 0,
                "cancelled_count": 0,
            },
            "registration_stat": {
                "pending_count": 0,
                "confirmed_count": 0,
            },
            "recommendation_summary": {},
            "labels": {},
            "has_ieee_ecopyright_consent": False,
        }

        paper_service_create.assert_called_once()
        call_kwargs = paper_service_create.call_args.kwargs
        assert call_kwargs["track"] == track
        assert call_kwargs["owner"] == conference_chair

    def test_conference_admin_bypasses_submissions_enabled(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper_service_create: MagicMock,
    ) -> None:
        update_object(track, submissions_enabled=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Invited Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    def test_track_admin_bypasses_submissions_enabled_for_own_track(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(track, submissions_enabled=False)
        api_client.force_login(track_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Track Admin Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    def test_track_admin_blocked_for_other_closed_track(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        code_pool: CodePool,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        other_track = Track.objects.create(
            conference=conference,
            code_pool=code_pool,
            display_name=faker.word(),
            visibility=TrackVisibility.PUBLIC,
            submissions_enabled=False,
        )
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(track_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(other_track.uid),
                "title": "Paper in Other Track",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert "do not have permission" in error["msg"]

        paper_service_create.assert_not_called()

    def test_track_admin_allowed_for_other_open_track(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        code_pool: CodePool,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        other_track = Track.objects.create(
            conference=conference,
            code_pool=code_pool,
            display_name=faker.word(),
            visibility=TrackVisibility.PUBLIC,
            submissions_enabled=True,
        )
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(track_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(other_track.uid),
                "title": "Paper in Open Track",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    def test_global_admin_bypasses_submissions_enabled(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        update_object(track, submissions_enabled=False)
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Global Admin Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        paper_service_create.assert_not_called()

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_create.assert_not_called()

    def test_authorization_global_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=GlobalRole.ADMIN)
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
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
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
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
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_authorization_conference_non_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper_service_create: MagicMock,
        non_admin_role: ConferenceRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_create.assert_not_called()

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
        paper_service_create: MagicMock,
        non_admin_role: TrackRole,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=non_admin_role,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Test Paper",
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        paper_service_create.assert_not_called()

    def test_auto_claim(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper_service_create: MagicMock,
    ) -> None:
        claim_service_set = mocker.spy(ClaimService, "set_claim")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Claimed Paper",
                "auto_claim": True,
                "authors": [
                    {
                        "given_name": "Alice",
                        "family_name": "Smith",
                        "email": "alice@example.com",
                        "corresponding": True,
                    },
                ],
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()
        claim_service_set.assert_called_once_with(paper=mocker.ANY)

    def test_auto_claim_false_by_default(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper_service_create: MagicMock,
    ) -> None:
        claim_service_set = mocker.spy(ClaimService, "set_claim")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Normal Paper",
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        paper_service_create.assert_called_once()
        claim_service_set.assert_not_called()

    def test_auto_claim_value_error(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        mocker.patch.object(
            ClaimService,
            "set_claim",
            side_effect=ValueError("Paper must have exactly one corresponding author."),
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Bad Claim Paper",
                "auto_claim": True,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "auto_claim"]
        assert "corresponding author" in error["msg"]

    def test_auto_claim_failure_rolls_back_paper(
        self,
        mocker: MockerFixture,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        mocker.patch.object(
            ClaimService,
            "set_claim",
            side_effect=ValueError("Paper must have exactly one corresponding author."),
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={
                "track": str(track.uid),
                "title": "Rolled Back Paper",
                "auto_claim": True,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert not Paper.objects.filter(title="Rolled Back Paper").exists()

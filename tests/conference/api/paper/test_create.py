from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import CodePool, Conference, Keyword, Paper, Track
from app.conference.services import KeywordService, PaperService
from app.core.models import User
from app.utils.enums import Region
from tests.helpers import any_str, approx_now, update_object


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
        visibility=Track.Visibility.PUBLIC,
        accepts_submissions=True,
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
                        "region_code": Region.US.name,
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
            "state": Paper.State.DRAFT,
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
            visibility=Track.Visibility.ADMIN_ONLY,
            accepts_submissions=True,
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
        update_object(track, accepts_submissions=False)
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
            visibility=Conference.Visibility.ADMIN_ONLY,
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

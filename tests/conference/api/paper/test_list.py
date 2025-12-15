from datetime import datetime
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from app.conference.models import Conference, Paper, PaperAuthor, Track
from app.core.models import User
from app.utils.enums import Region


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


def create_paper(
    conference: Conference,
    track: Track,
    owner: User,
    *,
    code: str = "PAPER-001",
    state: Paper.State = Paper.State.DRAFT,
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
                    "state": Paper.State.DRAFT,
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
        update_object(track, visibility=Track.Visibility.ADMIN_ONLY)
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
            visibility=Conference.Visibility.PUBLIC,
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
            visibility=Conference.Visibility.MEMBER_ONLY,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(hidden_conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize("state", Paper.State)
    def test_visible_state_when_announced(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        state: Paper.State,
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
        track: Track,
        actual_state: Paper.State,
        expected_state: Paper.State,
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

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import approx_now, update_object


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
    )


@pytest.mark.django_db
class TestDeleteMyPaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:delete-my-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time == approx_now()

    def test_deletes_submitted_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, state=Paper.State.SUBMITTED)
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time == approx_now()

    @pytest.mark.parametrize(
        "state",
        [
            Paper.State.UNDER_REVIEW,
            Paper.State.REJECTED,
            Paper.State.ACCEPTED,
            Paper.State.ACCEPTED_REVISION_NEEDED,
        ],
    )
    def test_rejects_non_draft_submitted_state(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert (
            response.json()["message"]
            == "Paper must be in Draft or Submitted state to delete."
        )

        paper.refresh_from_db()
        assert paper.delete_time is None

    def test_rejects_withdrawn_paper(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Withdrawn papers cannot be deleted."

        paper.refresh_from_db()
        assert paper.delete_time is None

    def test_paper_not_found(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, "NONEXISTENT"))
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

        response = api_client.delete(self.path(conference.name, paper.code))
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

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(self, api_client: Client, user: User) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path("nonexistent-conference", "PAPER-001"))
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

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


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
class TestDeletePaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse("api-1.0.0:delete-paper", args=[conference_name, paper_code])

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time == approx_now()

    @pytest.mark.parametrize(
        "state",
        [state for state in Paper.State if state not in Paper.State.decided()],
    )
    def test_track_admin_can_delete_non_decided(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(paper, state=state)
        api_client.force_login(track_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time == approx_now()

    @pytest.mark.parametrize("state", Paper.State.decided())
    def test_track_admin_cannot_delete_decided_paper(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        paper: Paper,
        state: Paper.State,
    ) -> None:
        track_admin = User.objects.create_user(username="track-admin")
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        update_object(paper, state=state)
        api_client.force_login(track_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == (
            "Track admins can only delete papers in Draft, Submitted, "
            "or Under Review state."
        )

        paper.refresh_from_db()
        assert paper.delete_time is None

    @pytest.mark.parametrize("state", Paper.State)
    def test_global_admin_can_delete_any_state(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        global_admin: User,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time is not None

    @pytest.mark.parametrize("state", Paper.State)
    def test_conference_admin_can_delete_any_state(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_admin: User,
        state: Paper.State,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(conference_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

        paper.refresh_from_db()
        assert paper.delete_time is not None

    def test_rejects_withdrawn_paper(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_admin: User,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert response.json()["message"] == "Withdrawn papers cannot be deleted."

        paper.refresh_from_db()
        assert paper.delete_time is None

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.delete(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_admin: User,
    ) -> None:
        api_client.force_login(conference_admin)

        response = api_client.delete(self.path("nonexistent-conference", "PAPER-001"))
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

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        admin = User.objects.create_user(username="global-admin")
        GlobalRoleAssignment.objects.create(user=admin, role=GlobalRole.ADMIN)
        api_client.force_login(admin)

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

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

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

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

        response = api_client.delete(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.NO_CONTENT

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

        response = api_client.delete(self.path(conference.name, "PAPER-001"))
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

        response = api_client.delete(self.path(conference.name, "PAPER-001"))
        assert response.status_code == HTTPStatus.FORBIDDEN

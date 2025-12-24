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
    Profile,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import RoleAssignmentService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region


@pytest.fixture
def mock_visible_users(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(RoleAssignmentService, "visible_users_with_roles")


@pytest.fixture
def mock_visible_conference_assignments(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(
        RoleAssignmentService,
        "visible_conference_role_assignments",
    )


@pytest.fixture
def mock_visible_track_assignments(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(RoleAssignmentService, "visible_track_role_assignments")


@pytest.mark.django_db
class TestListRoleAssignments:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-role-assignments", args=[conference_name])

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        mock_visible_users: AsyncMock,
        mock_visible_conference_assignments: AsyncMock,
        mock_visible_track_assignments: AsyncMock,
    ) -> None:
        user_with_profile = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(
            user=user_with_profile,
            given_name="Alice",
            family_name="Smith",
            affiliation="University of Example",
            region_code=Region.US.name,
        )
        conference_assignment = ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user_with_profile,
            role=ConferenceRole.CHAIR,
        )
        user_without_profile = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        track_assignment = TrackRoleAssignment.objects.create(
            track=track,
            user=user_without_profile,
            role=TrackRole.REVIEWER,
        )
        mock_visible_users.return_value = User.objects.filter(
            pk__in=[user_with_profile.pk, user_without_profile.pk]
        )
        mock_visible_conference_assignments.return_value = (
            ConferenceRoleAssignment.objects.filter(pk=conference_assignment.pk)
        )
        mock_visible_track_assignments.return_value = (
            TrackRoleAssignment.objects.filter(pk=track_assignment.pk)
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert len(data["items"]) == 2
        items_by_uid = {item["uid"]: item for item in data["items"]}
        assert items_by_uid[str(user_without_profile.uid)] == {
            "uid": str(user_without_profile.uid),
            "email": user_without_profile.email,
            "conference_roles": [],
            "track_roles": [
                {
                    "track": str(track.uid),
                    "role": TrackRole.REVIEWER,
                }
            ],
        }
        assert items_by_uid[str(user_with_profile.uid)] == {
            "uid": str(user_with_profile.uid),
            "email": user_with_profile.email,
            "profile": {
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "University of Example",
                "region_code": "US",
            },
            "conference_roles": [ConferenceRole.CHAIR],
            "track_roles": [],
        }

        mock_visible_users.assert_awaited_once_with(conference, conference_chair)
        mock_visible_conference_assignments.assert_awaited_once_with(
            conference,
            conference_chair,
        )
        mock_visible_track_assignments.assert_awaited_once_with(
            conference,
            conference_chair,
        )

    def test_pagination(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_users: AsyncMock,
        mock_visible_conference_assignments: AsyncMock,
        mock_visible_track_assignments: AsyncMock,
    ) -> None:
        users = [
            User.objects.create_user(
                username=faker.user_name(),
                email=faker.email(),
            )
            for _ in range(3)
        ]
        mock_visible_users.return_value = User.objects.filter(
            pk__in=[u.pk for u in users]
        )
        mock_visible_conference_assignments.return_value = (
            ConferenceRoleAssignment.objects.filter(pk=-1)
        )
        mock_visible_track_assignments.return_value = TrackRoleAssignment.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name), {"page_size": 2})
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert len(data["items"]) == 2
        assert "next_page_token" in data
        assert data["next_page_token"] is not None

        next_response = api_client.get(
            self.path(conference.name),
            {"page_size": 2, "page_token": data["next_page_token"]},
        )
        assert next_response.status_code == HTTPStatus.OK

        next_data = next_response.json()
        assert len(next_data["items"]) == 1

    def test_returns_empty_list_when_no_users_with_roles(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        mock_visible_users: AsyncMock,
        mock_visible_conference_assignments: AsyncMock,
        mock_visible_track_assignments: AsyncMock,
    ) -> None:
        mock_visible_users.return_value = User.objects.filter(pk=-1)
        mock_visible_conference_assignments.return_value = (
            ConferenceRoleAssignment.objects.none()
        )
        mock_visible_track_assignments.return_value = TrackRoleAssignment.objects.none()
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["items"] == []

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent-conference"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_authenticated_user_without_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=admin,
            role=global_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
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
        track_role: TrackRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=admin,
            role=track_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_track_admin_visibility_real_data(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        other_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=True,
        )
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        user_on_admin_track = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user_on_admin_track,
            role=ConferenceRole.CHAIR,
        )
        TrackRoleAssignment.objects.create(
            track=track,
            user=user_on_admin_track,
            role=TrackRole.REVIEWER,
        )
        user_only_conference_role = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user_only_conference_role,
            role=ConferenceRole.SECRETARY,
        )
        user_on_other_track = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        TrackRoleAssignment.objects.create(
            track=other_track,
            user=user_on_other_track,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(track_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        items_by_uid = {item["uid"]: item for item in data["items"]}
        assert str(user_on_admin_track.uid) in items_by_uid
        assert str(user_only_conference_role.uid) not in items_by_uid
        assert str(user_on_other_track.uid) not in items_by_uid
        assert items_by_uid[str(user_on_admin_track.uid)] == {
            "uid": str(user_on_admin_track.uid),
            "email": user_on_admin_track.email,
            "conference_roles": [],
            "track_roles": [
                {"track": str(track.uid), "role": TrackRole.REVIEWER},
            ],
        }

    def test_inactive_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        inactive_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        inactive_track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=inactive_track,
            user=inactive_track_admin,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(inactive_track_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

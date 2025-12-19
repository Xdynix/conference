from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import RoleAssignmentService
from app.conference.services.conference import InsufficientRolePermission
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture
def target_user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


@pytest.fixture
def mock_visible_conference_assignments(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(
        RoleAssignmentService,
        "visible_conference_role_assignments",
        return_value=ConferenceRoleAssignment.objects.none(),
    )


@pytest.fixture
def mock_visible_track_assignments(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(
        RoleAssignmentService,
        "visible_track_role_assignments",
        return_value=TrackRoleAssignment.objects.none(),
    )


@pytest.mark.django_db
class TestMutateRoleAssignment:
    @classmethod
    def path(cls, conference_name: str, user_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:mutate-role-assignment",
            args=[conference_name, user_uid],
        )

    def test_add_conference_role_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
        mock_visible_conference_assignments: MagicMock,
        mock_visible_track_assignments: MagicMock,
    ) -> None:
        add_conference_role_spy = mocker.spy(
            RoleAssignmentService,
            "add_conference_role",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(target_user.uid)
        assert data["username"] == target_user.username
        assert data["email"] == target_user.email
        assert data["conference_roles"] == []
        assert data["track_roles"] == []

        add_conference_role_spy.assert_called_once_with(
            conference=conference,
            target_user=target_user,
            role=ConferenceRole.CHAIR,
            requesting_user=global_admin,
        )
        mock_visible_conference_assignments.assert_awaited_once()
        mock_visible_track_assignments.assert_awaited_once()

    def test_remove_conference_role_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        remove_conference_role_spy = mocker.spy(
            RoleAssignmentService,
            "remove_conference_role",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "remove_conference_role",
                "role": ConferenceRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.OK

        remove_conference_role_spy.assert_called_once_with(
            conference=conference,
            target_user=target_user,
            role=ConferenceRole.REVIEWER,
            requesting_user=global_admin,
        )

    def test_add_track_role_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        target_user: User,
    ) -> None:
        add_track_role_spy = mocker.spy(
            RoleAssignmentService,
            "add_track_role",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(track.uid),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.OK

        add_track_role_spy.assert_called_once_with(
            conference=conference,
            track=track,
            target_user=target_user,
            role=TrackRole.REVIEWER,
            requesting_user=global_admin,
        )

    def test_remove_track_role_happy_path(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        target_user: User,
    ) -> None:
        remove_track_role_spy = mocker.spy(
            RoleAssignmentService,
            "remove_track_role",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "remove_track_role",
                "track": str(track.uid),
                "role": TrackRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.OK

        remove_track_role_spy.assert_called_once_with(
            conference=conference,
            track=track,
            target_user=target_user,
            role=TrackRole.CHAIR,
            requesting_user=global_admin,
        )

    def test_invalid_track(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(ULID()),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert error["msg"] == "Invalid track UID."

    def test_inactive_track_rejected(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        inactive_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(inactive_track.uid),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert error["msg"] == "Invalid track UID."

    def test_track_from_different_conference_rejected(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
            active=True,
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(other_track.uid),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert error["msg"] == "Invalid track UID."

    def test_track_ignored_for_conference_action(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        add_conference_role_spy = mocker.spy(
            RoleAssignmentService,
            "add_conference_role",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
                "track": str(ULID()),
            },
        )
        assert response.status_code == HTTPStatus.OK

        add_conference_role_spy.assert_called_once_with(
            conference=conference,
            target_user=target_user,
            role=ConferenceRole.CHAIR,
            requesting_user=global_admin,
        )

    def test_insufficient_permission_raises_forbidden(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        mocker.patch.object(
            RoleAssignmentService,
            "add_conference_role",
            side_effect=InsufficientRolePermission("Cannot assign this role"),
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

        data = response.json()
        assert data["message"] == "Cannot assign this role"

    def test_unknown_action_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        target_user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "unknown_action",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload"]
        assert "unknown_action" in error["msg"]

    def test_service_value_error_raises_validation_error(
        self,
        mocker: MockerFixture,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
        target_user: User,
    ) -> None:
        mocker.patch.object(
            RoleAssignmentService,
            "add_track_role",
            side_effect=ValueError("Track validation failed"),
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(track.uid),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "track"]
        assert error["msg"] == "Track validation failed"

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        target_user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path("nonexistent-conference", target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_user_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, ULID()),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        target_user: User,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        target_user: User,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        target_user: User,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=GlobalRole.ADMIN)
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.CHAIR,
            },
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        target_user: User,
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
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_conference_role",
                "role": ConferenceRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    def test_authorization_track_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
        target_user: User,
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
            self.path(conference.name, target_user.uid),
            data={
                "action": "add_track_role",
                "track": str(track.uid),
                "role": TrackRole.REVIEWER,
            },
        )
        assert response.status_code == HTTPStatus.OK

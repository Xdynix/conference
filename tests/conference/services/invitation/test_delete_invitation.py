from unittest.mock import MagicMock

import pytest
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Track,
    TrackRole,
)
from app.conference.services import ConferenceService, InvitationService
from app.conference.services.conference import InsufficientRolePermission
from app.core.models import GlobalRole, GlobalRoleAssignment, User

from .conftest import add_invitation_roles


@pytest.mark.django_db
class TestInvitationServiceDeleteInvitation:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.fixture
    def invitation_with_roles(
        self,
        faker: Faker,
        conference: Conference,
        track: Track,
    ) -> Invitation:
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track: [TrackRole.CHAIR]},
        )
        return invitation

    @pytest.fixture
    def mock_validate_roles(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(ConferenceService, "validate_can_assign_roles")

    def test_happy_path(
        self,
        user: User,
        track: Track,
        invitation_with_roles: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        InvitationService.delete_invitation(
            invitation_uid=invitation_with_roles.uid,
            user=user,
        )

        assert not Invitation.objects.filter(pk=invitation_with_roles.pk).exists()
        assert not InvitationConferenceRoleEntry.objects.filter(
            invitation=invitation_with_roles
        ).exists()
        assert not InvitationTrackRoleEntry.objects.filter(
            invitation=invitation_with_roles
        ).exists()

        mock_validate_roles.assert_called_once_with(
            user=user,
            conference=invitation_with_roles.conference,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track: [TrackRole.CHAIR]},
        )

    def test_insufficient_permission(
        self,
        user: User,
        invitation_with_roles: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        mock_validate_roles.side_effect = InsufficientRolePermission(
            "Cannot assign CHAIR role"
        )

        with pytest.raises(
            InsufficientRolePermission,
            match="You cannot manage this invitation",
        ):
            InvitationService.delete_invitation(
                invitation_uid=invitation_with_roles.uid,
                user=user,
            )

        assert Invitation.objects.filter(pk=invitation_with_roles.pk).exists()
        assert InvitationConferenceRoleEntry.objects.filter(
            invitation=invitation_with_roles
        ).exists()
        assert InvitationTrackRoleEntry.objects.filter(
            invitation=invitation_with_roles
        ).exists()

        assert mock_validate_roles.call_count == 1

    def test_raises_does_not_exist_for_invalid_uid(self, user: User) -> None:
        with pytest.raises(Invitation.DoesNotExist):
            InvitationService.delete_invitation(
                invitation_uid=ULID(),
                user=user,
            )

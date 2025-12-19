from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
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
from app.conference.services import InvitationService
from app.conference.services.conference import InsufficientRolePermission
from app.core.models import User


@pytest.fixture
def mock_visible(mocker: MockerFixture, invitation: Invitation) -> MagicMock:
    return mocker.patch.object(
        InvitationService,
        "visible_invitations",
        return_value=Invitation.objects.filter(pk=invitation.pk),
    )


@pytest.fixture
def invitation_service_delete(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(InvitationService, "delete_invitation")


@pytest.mark.django_db
class TestDeleteInvitation:
    @classmethod
    def path(cls, conference_name: str, invitation_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:delete-invitation",
            args=[conference_name, invitation_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        track: Track,
        mock_visible: MagicMock,
        invitation_service_delete: MagicMock,
    ) -> None:
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.REVIEWER,
        )
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not Invitation.objects.filter(pk=invitation.pk).exists()
        assert not InvitationConferenceRoleEntry.objects.filter(
            invitation=invitation
        ).exists()
        assert not InvitationTrackRoleEntry.objects.filter(
            invitation=invitation
        ).exists()

        mock_visible.assert_awaited_once_with(conference, global_admin)
        invitation_service_delete.assert_called_once_with(
            invitation_uid=invitation.uid,
            user=global_admin,
        )

    def test_not_found_when_not_visible(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
        invitation_service_delete: MagicMock,
    ) -> None:
        mock_visible.return_value = Invitation.objects.none()
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        invitation_service_delete.assert_not_called()

    def test_handle_insufficient_permission(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation: Invitation,
        mock_visible: MagicMock,
        invitation_service_delete: MagicMock,
    ) -> None:
        invitation_service_delete.side_effect = InsufficientRolePermission(
            "You cannot manage this invitation"
        )
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, invitation.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert response.json()["message"] == "You cannot manage this invitation"

        assert Invitation.objects.filter(pk=invitation.pk).exists()

        mock_visible.assert_awaited_once_with(conference, global_admin)

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        invitation: Invitation,
        invitation_service_delete: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path("missing", invitation.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        invitation_service_delete.assert_not_called()

    def test_invitation_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        invitation_service_delete: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

        invitation_service_delete.assert_not_called()

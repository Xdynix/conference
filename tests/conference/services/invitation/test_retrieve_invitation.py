import pytest
from django.core.signing import BadSignature
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Invitation
from app.conference.services import InvitationService
from tests.helpers import update_object


@pytest.mark.django_db
class TestInvitationServiceRetrieveInvitation:
    def test_happy_path(self, invitation: Invitation) -> None:
        token = InvitationService.get_invitation_token(invitation)

        result = InvitationService.retrieve_invitation(token)

        assert result == invitation

    def test_returns_none_for_invalid_token(self) -> None:
        invalid_token = "invalid:token:signature"

        result = InvitationService.retrieve_invitation(invalid_token)

        assert result is None

    def test_returns_none_for_tampered_token(
        self,
        invitation: Invitation,
    ) -> None:
        token = InvitationService.get_invitation_token(invitation)
        tampered_token = token[:-6] + "foobar"

        result = InvitationService.retrieve_invitation(tampered_token)

        assert result is None

    def test_returns_none_for_nonexistent_invitation(
        self,
        mocker: MockerFixture,
    ) -> None:
        mock_unsign = mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            return_value=ULID(),
        )
        fake_token = "fake:token"

        result = InvitationService.retrieve_invitation(fake_token)

        assert result is None
        mock_unsign.assert_called_once_with(fake_token)

    def test_handles_bad_signature_exception(
        self,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            side_effect=BadSignature("Invalid signature"),
        )

        result = InvitationService.retrieve_invitation("bad:token")

        assert result is None

    def test_returns_none_for_inactive_conference(
        self,
        invitation: Invitation,
    ) -> None:
        update_object(invitation.conference, active=False)
        token = InvitationService.get_invitation_token(invitation)

        result = InvitationService.retrieve_invitation(token)

        assert result is None

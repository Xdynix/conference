import pytest
from faker import Faker

from app.conference.models import Conference, Invitation
from app.conference.services import InvitationService


@pytest.mark.django_db
class TestInvitationServiceGetInvitationToken:
    def test_happy_path(self, invitation: Invitation) -> None:
        token = InvitationService.get_invitation_token(invitation)

        assert isinstance(token, str)
        assert len(token) > 0
        assert ":" in token

    def test_token_is_deterministic(self, invitation: Invitation) -> None:
        token1 = InvitationService.get_invitation_token(invitation)
        token2 = InvitationService.get_invitation_token(invitation)

        assert token1 == token2

    def test_different_invitations_produce_different_tokens(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        invitation1 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        invitation2 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )

        token1 = InvitationService.get_invitation_token(invitation1)
        token2 = InvitationService.get_invitation_token(invitation2)

        assert token1 != token2

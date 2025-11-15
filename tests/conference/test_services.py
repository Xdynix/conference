from collections.abc import Iterable, Mapping

import pytest
from django.core.signing import BadSignature
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import InvitationService
from app.core.models import User
from tests.helpers import approx_now, update_object


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.mark.django_db
class TestInvitationServiceGetInvitationToken:
    @pytest.fixture
    def inviter(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

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
        inviter: User,
    ) -> None:
        invitation1 = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )
        invitation2 = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

        token1 = InvitationService.get_invitation_token(invitation1)
        token2 = InvitationService.get_invitation_token(invitation2)

        assert token1 != token2


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceRetrieveInvitation:
    @pytest.fixture
    def inviter(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

    async def test_happy_path(self, invitation: Invitation) -> None:
        token = InvitationService.get_invitation_token(invitation)

        result = await InvitationService.retrieve_invitation(token)

        assert result == invitation

    async def test_returns_none_for_invalid_token(self) -> None:
        invalid_token = "invalid:token:signature"

        result = await InvitationService.retrieve_invitation(invalid_token)

        assert result is None

    async def test_returns_none_for_tampered_token(
        self,
        invitation: Invitation,
    ) -> None:
        token = InvitationService.get_invitation_token(invitation)
        tampered_token = token[:-6] + "foobar"

        result = await InvitationService.retrieve_invitation(tampered_token)

        assert result is None

    async def test_returns_none_for_nonexistent_invitation(
        self,
        mocker: MockerFixture,
    ) -> None:
        mock_unsign = mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            return_value=ULID(),
        )
        fake_token = "fake:token"

        result = await InvitationService.retrieve_invitation(fake_token)

        assert result is None
        mock_unsign.assert_called_once_with(fake_token)

    async def test_handles_bad_signature_exception(
        self,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            side_effect=BadSignature("Invalid signature"),
        )

        result = await InvitationService.retrieve_invitation("bad:token")

        assert result is None


def add_invitation_roles(
    invitation: Invitation,
    *,
    conference_roles: Iterable[ConferenceRole] = (),
    track_roles: Mapping[Track, Iterable[TrackRole]] | None = None,
) -> None:
    for conference_role in conference_roles:
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=conference_role,
        )
    for track, roles in (track_roles or {}).items():
        for track_role in roles:
            InvitationTrackRoleEntry.objects.create(
                invitation=invitation,
                track=track,
                role=track_role,
            )


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceRedeemInvitation:
    @pytest.fixture
    def inviter(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def invitee(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

    def test_happy_path(self, invitee: User, invitation: Invitation) -> None:
        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_returns_false_when_already_accepted(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        update_object(
            invitation,
            invitee_user=invitee,
            accept_time=timezone.now(),
        )
        original_accept_time = invitation.accept_time
        original_update_time = invitation.update_time

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is False

        invitation.refresh_from_db()
        assert invitation.accept_time == original_accept_time
        assert invitation.update_time == original_update_time

    def test_returns_true_when_already_rejected(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        update_object(invitation, reject_time=timezone.now())

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_assigns_conference_roles(
        self,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=ConferenceRole.CHAIR,
        ).exists()
        assert ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=ConferenceRole.REVIEWER,
        ).exists()

    def test_assigns_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        track1 = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        track2 = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            track_roles={
                track1: [TrackRole.SECRETARY, TrackRole.REVIEWER],
                track2: [TrackRole.SECRETARY],
            },
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=TrackRole.SECRETARY,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=TrackRole.REVIEWER,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track2,
            role=TrackRole.SECRETARY,
        ).exists()

    def test_ignores_duplicate_role_assignments(
        self,
        conference: Conference,
        track: Track,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            user=invitee,
            conference=conference,
            role=ConferenceRole.CHAIR,
        )
        TrackRoleAssignment.objects.create(
            user=invitee,
            track=track,
            role=TrackRole.SECRETARY,
        )
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR],
            track_roles={track: [TrackRole.SECRETARY]},
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert (
            ConferenceRoleAssignment.objects.filter(
                user=invitee,
                conference=conference,
                role=ConferenceRole.CHAIR,
            ).count()
            == 1
        )
        assert (
            TrackRoleAssignment.objects.filter(
                user=invitee,
                track=track,
                role=TrackRole.SECRETARY,
            ).count()
            == 1
        )

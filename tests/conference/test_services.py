from collections.abc import Iterable, Mapping

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
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
from app.conference.services import ConferenceService, InvitationService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import approx_now, update_object

a_update_object = sync_to_async(update_object)


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


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


@pytest.mark.django_db(transaction=True)
class TestConferenceServiceVisibleConferences:
    async def test_anonymous_user_only_sees_public_conferences(self) -> None:
        public = await Conference.objects.acreate(
            name="public-conf",
            display_name="Public",
            visibility=Conference.Visibility.PUBLIC,
        )
        await Conference.objects.acreate(
            name="private-conf",
            display_name="Private",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await Conference.objects.acreate(
            name="inactive-conf",
            display_name="Inactive",
            visibility=Conference.Visibility.PUBLIC,
            active=False,
        )

        qs = await ConferenceService.visible_conferences(AnonymousUser())
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == [public]

    async def test_superuser_sees_all_active_conferences(self, user: User) -> None:
        public = await Conference.objects.acreate(
            name="public-conf",
            display_name="Public",
            visibility=Conference.Visibility.PUBLIC,
        )
        private = await Conference.objects.acreate(
            name="private-conf",
            display_name="Private",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await Conference.objects.acreate(
            name="inactive-conf",
            display_name="Inactive",
            visibility=Conference.Visibility.PUBLIC,
            active=False,
        )
        await a_update_object(user, is_superuser=True)

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == [private, public]

    async def test_global_admin_role_grants_full_visibility(self, user: User) -> None:
        private = await Conference.objects.acreate(
            name="secure-conf",
            display_name="Secure",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.ADMIN)

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == [private]

    async def test_conference_admin_sees_private_conference(self, user: User) -> None:
        visible = await Conference.objects.acreate(
            name="visible-conf",
            display_name="Visible",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await Conference.objects.acreate(
            name="other-conf",
            display_name="Other",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=visible,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == [visible]

    async def test_track_admin_gains_conference_visibility(self, user: User) -> None:
        target = await Conference.objects.acreate(
            name="target-conf",
            display_name="Target",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        await Conference.objects.acreate(
            name="other-conf",
            display_name="Other",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        track = await Track.objects.acreate(
            conference=target,
            display_name="Visible Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == [target]


@pytest.mark.django_db(transaction=True)
class TestConferenceServiceVisibleTracks:
    async def test_anonymous_user_sees_only_public_tracks(
        self,
        conference: Conference,
    ) -> None:
        public_track = await Track.objects.acreate(
            conference=conference,
            display_name="Public Track",
            visibility=Track.Visibility.PUBLIC,
        )
        await Track.objects.acreate(
            conference=conference,
            display_name="Private Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )

        qs = await ConferenceService.visible_tracks(AnonymousUser(), [conference])
        tracks = [track async for track in qs]

        assert tracks == [public_track]

    async def test_superuser_sees_all_tracks(
        self, user: User, conference: Conference
    ) -> None:
        first_track = await Track.objects.acreate(
            conference=conference,
            display_name="First",
            ordering=1,
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        second_track = await Track.objects.acreate(
            conference=conference,
            display_name="Second",
            ordering=2,
            visibility=Track.Visibility.PUBLIC,
        )
        await a_update_object(user, is_superuser=True)

        qs = await ConferenceService.visible_tracks(user, [conference])
        tracks = [track async for track in qs]

        assert tracks == [first_track, second_track]

    async def test_global_admin_role_sees_all_tracks(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        private_track = await Track.objects.acreate(
            conference=conference,
            display_name="Private Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.READ_ALL)

        qs = await ConferenceService.visible_tracks(user, [conference])
        tracks = [track async for track in qs]

        assert tracks == [private_track]

    async def test_conference_admin_sees_private_tracks(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        public_track = await Track.objects.acreate(
            conference=conference,
            display_name="Public",
            ordering=1,
            visibility=Track.Visibility.PUBLIC,
        )
        private_track = await Track.objects.acreate(
            conference=conference,
            display_name="Private",
            ordering=2,
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        qs = await ConferenceService.visible_tracks(user, [conference])
        tracks = [track async for track in qs]

        assert tracks == [public_track, private_track]

    async def test_track_admin_sees_assigned_private_track(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        assigned_track = await Track.objects.acreate(
            conference=conference,
            display_name="Assigned",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await Track.objects.acreate(
            conference=conference,
            display_name="Hidden",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await TrackRoleAssignment.objects.acreate(
            track=assigned_track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await ConferenceService.visible_tracks(user, [conference])
        tracks = [track async for track in qs]

        assert tracks == [assigned_track]

    async def test_inactive_items_are_filtered(self, user: User) -> None:
        active_conference = await Conference.objects.acreate(
            name="active-conf",
            display_name="Active",
        )
        inactive_conference = await Conference.objects.acreate(
            name="inactive-conf",
            display_name="Inactive",
            active=False,
        )
        active_track = await Track.objects.acreate(
            conference=active_conference,
            display_name="Active",
            visibility=Track.Visibility.PUBLIC,
        )
        await Track.objects.acreate(
            conference=active_conference,
            display_name="Inactive Track",
            visibility=Track.Visibility.PUBLIC,
            active=False,
        )
        await Track.objects.acreate(
            conference=inactive_conference,
            display_name="Hidden",
            visibility=Track.Visibility.PUBLIC,
        )
        await a_update_object(user, is_superuser=True)

        qs = await ConferenceService.visible_tracks(
            user,
            [active_conference, inactive_conference],
        )
        tracks = [track async for track in qs]

        assert tracks == [active_track]


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

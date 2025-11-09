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
    InvitationTrackEntry,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferencePermissionService, InvitationService
from app.core.models import Permission, User
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


@pytest.mark.django_db(transaction=True)
class TestConferencePermissionServiceGetConferencePermissions:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def perm_read(self) -> Permission:
        return Permission.objects.create(key="conference.read")

    @pytest.fixture
    def perm_write(self) -> Permission:
        return Permission.objects.create(key="conference.write")

    @pytest.fixture
    def perm_admin(self) -> Permission:
        return Permission.objects.create(key="conference.admin")

    @pytest.fixture
    def conference_role_viewer(self, perm_read: Permission) -> ConferenceRole:
        role = ConferenceRole.objects.create(
            name="viewer",
            display_name="Conference Viewer",
        )
        role.permissions.add(perm_read)
        return role

    @pytest.fixture
    def conference_role_admin(
        self,
        perm_read: Permission,
        perm_write: Permission,
        perm_admin: Permission,
    ) -> ConferenceRole:
        role = ConferenceRole.objects.create(
            name="admin",
            display_name="Conference Admin",
        )
        role.permissions.add(perm_read, perm_write, perm_admin)
        return role

    async def test_no_assignments(self, user: User, conference: Conference) -> None:
        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == set()

    async def test_single_conference_role(
        self,
        user: User,
        conference: Conference,
        conference_role_viewer: ConferenceRole,
    ) -> None:
        await ConferenceRoleAssignment.objects.acreate(
            user=user,
            conference=conference,
            role=conference_role_viewer,
        )

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == {"conference.read"}

    async def test_multiple_conference_roles(
        self,
        user: User,
        conference: Conference,
        conference_role_viewer: ConferenceRole,
        conference_role_admin: ConferenceRole,
    ) -> None:
        await ConferenceRoleAssignment.objects.acreate(
            user=user,
            conference=conference,
            role=conference_role_viewer,
        )
        await ConferenceRoleAssignment.objects.acreate(
            user=user,
            conference=conference,
            role=conference_role_admin,
        )

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == {
            "conference.read",
            "conference.write",
            "conference.admin",
        }

    async def test_different_conferences_isolated(
        self,
        faker: Faker,
        user: User,
        conference_role_viewer: ConferenceRole,
    ) -> None:
        conference1 = await Conference.objects.acreate(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = await Conference.objects.acreate(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        await ConferenceRoleAssignment.objects.acreate(
            user=user,
            conference=conference1,
            role=conference_role_viewer,
        )

        permissions1 = await ConferencePermissionService.get_conference_permissions(
            user,
            conference1,
        )
        permissions2 = await ConferencePermissionService.get_conference_permissions(
            user,
            conference2,
        )

        assert permissions1 == {"conference.read"}
        assert permissions2 == set()

    async def test_different_users_isolated(
        self,
        faker: Faker,
        conference: Conference,
        conference_role_viewer: ConferenceRole,
        conference_role_admin: ConferenceRole,
    ) -> None:
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())

        await ConferenceRoleAssignment.objects.acreate(
            user=user1,
            conference=conference,
            role=conference_role_viewer,
        )
        await ConferenceRoleAssignment.objects.acreate(
            user=user2,
            conference=conference,
            role=conference_role_admin,
        )

        permissions1 = await ConferencePermissionService.get_conference_permissions(
            user1,
            conference,
        )
        permissions2 = await ConferencePermissionService.get_conference_permissions(
            user2,
            conference,
        )

        assert permissions1 == {"conference.read"}
        assert permissions2 == {
            "conference.read",
            "conference.write",
            "conference.admin",
        }

    async def test_inactive_user(
        self,
        user: User,
        conference: Conference,
        conference_role_viewer: ConferenceRole,
    ) -> None:
        await sync_to_async(update_object)(user, is_active=False)
        await ConferenceRoleAssignment.objects.acreate(
            user=user,
            conference=conference,
            role=conference_role_viewer,
        )

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == set()

    async def test_anonymous_user(self, conference: Conference) -> None:
        user = AnonymousUser()

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == set()

    async def test_superuser(
        self,
        user: User,
        conference: Conference,
        perm_read: Permission,
        perm_write: Permission,
        perm_admin: Permission,
    ) -> None:
        await sync_to_async(update_object)(user, is_superuser=True)
        await Permission.objects.exclude(
            key__in=[perm_read.key, perm_write.key, perm_admin.key]
        ).adelete()

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == {
            "conference.read",
            "conference.write",
            "conference.admin",
        }

    async def test_inactive_superuser(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        await sync_to_async(update_object)(user, is_active=False, is_superuser=True)

        permissions = await ConferencePermissionService.get_conference_permissions(
            user,
            conference,
        )

        assert permissions == set()


@pytest.mark.django_db(transaction=True)
class TestConferencePermissionServiceGetTrackPermissions:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def perm_review(self) -> Permission:
        return Permission.objects.create(key="track.review")

    @pytest.fixture
    def perm_moderate(self) -> Permission:
        return Permission.objects.create(key="track.moderate")

    @pytest.fixture
    def track_role_reviewer(self, perm_review: Permission) -> TrackRole:
        role = TrackRole.objects.create(
            name="reviewer",
            display_name="Track Reviewer",
        )
        role.permissions.add(perm_review)
        return role

    @pytest.fixture
    def track_role_moderator(
        self,
        perm_review: Permission,
        perm_moderate: Permission,
    ) -> TrackRole:
        role = TrackRole.objects.create(
            name="moderator",
            display_name="Track Moderator",
        )
        role.permissions.add(perm_review, perm_moderate)
        return role

    async def test_no_assignments(self, user: User, track: Track) -> None:
        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == set()

    async def test_single_track_role(
        self,
        user: User,
        track: Track,
        track_role_reviewer: TrackRole,
    ) -> None:
        await TrackRoleAssignment.objects.acreate(
            user=user,
            track=track,
            role=track_role_reviewer,
        )

        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == {"track.review"}

    async def test_multiple_track_roles(
        self,
        user: User,
        track: Track,
        track_role_reviewer: TrackRole,
        track_role_moderator: TrackRole,
    ) -> None:
        await TrackRoleAssignment.objects.acreate(
            user=user,
            track=track,
            role=track_role_reviewer,
        )
        await TrackRoleAssignment.objects.acreate(
            user=user,
            track=track,
            role=track_role_moderator,
        )

        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == {"track.review", "track.moderate"}

    async def test_different_tracks_isolated(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track_role_reviewer: TrackRole,
    ) -> None:
        track1 = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        track2 = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )

        await TrackRoleAssignment.objects.acreate(
            user=user,
            track=track1,
            role=track_role_reviewer,
        )

        permissions1 = await ConferencePermissionService.get_track_permissions(
            user,
            track1,
        )
        permissions2 = await ConferencePermissionService.get_track_permissions(
            user,
            track2,
        )

        assert permissions1 == {"track.review"}
        assert permissions2 == set()

    async def test_inactive_user(
        self,
        user: User,
        track: Track,
        track_role_reviewer: TrackRole,
    ) -> None:
        await sync_to_async(update_object)(user, is_active=False)
        await TrackRoleAssignment.objects.acreate(
            user=user,
            track=track,
            role=track_role_reviewer,
        )

        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == set()

    async def test_anonymous_user(self, track: Track) -> None:
        user = AnonymousUser()

        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == set()

    async def test_superuser(
        self,
        user: User,
        track: Track,
        perm_review: Permission,
        perm_moderate: Permission,
    ) -> None:
        await sync_to_async(update_object)(user, is_superuser=True)
        await Permission.objects.exclude(
            key__in=[perm_review.key, perm_moderate.key]
        ).adelete()

        permissions = await ConferencePermissionService.get_track_permissions(
            user,
            track,
        )

        assert permissions == {"track.review", "track.moderate"}


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


async def add_invitation_roles(
    invitation: Invitation,
    *,
    conference_roles: Iterable[ConferenceRole] = (),
    track_roles: Mapping[Track, Iterable[TrackRole]] | None = None,
) -> None:
    await invitation.conference_roles.aadd(*conference_roles)
    for track, roles in (track_roles or {}).items():
        entry = await InvitationTrackEntry.objects.acreate(
            invitation=invitation,
            track=track,
        )
        await entry.roles.aadd(*roles)


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

    async def test_happy_path(self, invitee: User, invitation: Invitation) -> None:
        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is True
        await invitation.arefresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    async def test_returns_false_when_already_accepted(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        await sync_to_async(update_object)(
            invitation,
            invitee_user=invitee,
            accept_time=timezone.now(),
        )
        original_accept_time = invitation.accept_time
        original_update_time = invitation.update_time

        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is False
        await invitation.arefresh_from_db()
        assert invitation.accept_time == original_accept_time
        assert invitation.update_time == original_update_time

    async def test_returns_true_when_already_rejected(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        await sync_to_async(update_object)(
            invitation,
            reject_time=timezone.now(),
        )

        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is True
        await invitation.arefresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    async def test_assigns_conference_roles(
        self,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        role1 = await ConferenceRole.objects.acreate(
            name="reviewer",
            display_name="Reviewer",
        )
        role2 = await ConferenceRole.objects.acreate(
            name="chair",
            display_name="Chair",
        )
        await add_invitation_roles(invitation, conference_roles=[role1, role2])

        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is True
        assert await ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=role1,
        ).aexists()
        assert await ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=role2,
        ).aexists()

    async def test_assigns_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        role1 = await TrackRole.objects.acreate(
            name="reviewer",
            display_name="Reviewer",
        )
        role2 = await TrackRole.objects.acreate(
            name="chair",
            display_name="Chair",
        )
        track1 = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        track2 = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        await add_invitation_roles(
            invitation,
            track_roles={
                track1: [role1, role2],
                track2: [role1],
            },
        )

        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is True
        assert await TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=role1,
        ).aexists()
        assert await TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=role2,
        ).aexists()
        assert await TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track2,
            role=role1,
        ).aexists()

    async def test_ignores_duplicate_role_assignments(
        self,
        conference: Conference,
        track: Track,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        conference_role = await ConferenceRole.objects.acreate(
            name="reviewer",
            display_name="Reviewer",
        )
        track_role = await TrackRole.objects.acreate(
            name="chair",
            display_name="Chair",
        )
        await ConferenceRoleAssignment.objects.acreate(
            user=invitee,
            conference=conference,
            role=conference_role,
        )
        await TrackRoleAssignment.objects.acreate(
            user=invitee,
            track=track,
            role=track_role,
        )
        await add_invitation_roles(
            invitation,
            conference_roles=[conference_role],
            track_roles={track: [track_role]},
        )

        result = await InvitationService.redeem_invitation(invitation, invitee)

        assert result is True
        assert (
            await ConferenceRoleAssignment.objects.filter(
                user=invitee,
                conference=conference,
                role=conference_role,
            ).acount()
            == 1
        )
        assert (
            await TrackRoleAssignment.objects.filter(
                user=invitee,
                track=track,
                role=track_role,
            ).acount()
            == 1
        )

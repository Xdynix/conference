import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferencePermissionService
from app.core.models import Permission, User
from tests.helpers import update_object


@pytest.mark.django_db(transaction=True)
class TestConferencePermissionServiceGetConferencePermissions:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

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
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def track(self, conference: Conference, faker: Faker) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

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

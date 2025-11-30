import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import RoleAssignmentService
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track_a(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def track_b(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.mark.django_db(transaction=True)
class TestVisibleUsersWithRoles:
    async def test_superuser_sees_all_users_with_roles(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())

        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user1,
            role=ConferenceRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference, superuser
        )

        assert await result.acount() == 2
        assert {u async for u in result} == {user1, user2}

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_role_sees_all_users_with_roles(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        global_role: GlobalRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=user, role=global_role)
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())

        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user1,
            role=ConferenceRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(conference, user)

        assert await result.acount() == 2
        assert {u async for u in result} == {user1, user2}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_users_with_roles(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=conference_admin,
            role=conference_role,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user1,
            role=ConferenceRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            conference_admin,
        )

        assert await result.acount() == 3
        assert {u async for u in result} == {conference_admin, user1, user2}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_only_users_on_their_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        user_on_track_a = await User.objects.acreate_user(username=faker.user_name())
        user_on_track_b = await User.objects.acreate_user(username=faker.user_name())
        user_with_conference_role = await User.objects.acreate_user(
            username=faker.user_name()
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user_on_track_a,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user_on_track_b,
            role=TrackRole.REVIEWER,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user_with_conference_role,
            role=ConferenceRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            track_admin,
        )

        assert await result.acount() == 2
        assert {u async for u in result} == {track_admin, user_on_track_a}

    async def test_excludes_inactive_users(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        active_user = await User.objects.acreate_user(username=faker.user_name())
        inactive_user = await User.objects.acreate_user(
            username=faker.user_name(),
            is_active=False,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=active_user,
            role=ConferenceRole.CHAIR,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=inactive_user,
            role=ConferenceRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference, superuser
        )

        assert await result.acount() == 1
        assert {u async for u in result} == {active_user}

    async def test_excludes_users_with_only_inactive_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        user_on_active_track = await User.objects.acreate_user(
            username=faker.user_name()
        )
        user_on_inactive_track = await User.objects.acreate_user(
            username=faker.user_name()
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user_on_active_track,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user_on_inactive_track,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            superuser,
        )

        assert await result.acount() == 1
        assert {u async for u in result} == {user_on_active_track}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_of_inactive_track_sees_no_users(
        self,
        faker: Faker,
        conference: Conference,
        track_role: TrackRole,
    ) -> None:
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=track_admin,
            role=track_role,
        )
        user_on_inactive_track = await User.objects.acreate_user(
            username=faker.user_name()
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user_on_inactive_track,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            track_admin,
        )

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_of_both_active_and_inactive_tracks_sees_only_active(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=track_admin,
            role=track_role,
        )
        user_on_active = await User.objects.acreate_user(username=faker.user_name())
        user_on_inactive = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user_on_active,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user_on_inactive,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            track_admin,
        )

        # Should see: track_admin (has role on active track) + user_on_active
        # Should NOT see: user_on_inactive (only has role on inactive track)
        assert await result.acount() == 2
        assert {u async for u in result} == {track_admin, user_on_active}

    async def test_regular_user_sees_no_users(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        regular_user = await User.objects.acreate_user(username=faker.user_name())
        user_with_role = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user_with_role,
            role=ConferenceRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_users_with_roles(
            conference,
            regular_user,
        )

        assert await result.acount() == 0


@pytest.mark.django_db(transaction=True)
class TestVisibleConferenceRoleAssignments:
    async def test_superuser_sees_all_conference_assignments(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment1 = await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user1,
            role=ConferenceRole.CHAIR,
        )
        assignment2 = await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user2,
            role=ConferenceRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            superuser,
        )

        assert await result.acount() == 2
        assert {a async for a in result} == {assignment1, assignment2}

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_role_sees_all_conference_assignments(
        self,
        faker: Faker,
        conference: Conference,
        global_role: GlobalRole,
    ) -> None:
        global_user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=global_user, role=global_role)
        user = await User.objects.acreate_user(username=faker.user_name())
        assignment = await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            global_user,
        )

        assert await result.acount() == 1
        assert {a async for a in result} == {assignment}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_conference_assignments(
        self,
        faker: Faker,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=conference_admin,
            role=conference_role,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user1,
            role=ConferenceRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            conference_admin,
        )

        assert await result.acount() == 2  # admin's own + user1's

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_no_conference_assignments(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        user = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            track_admin,
        )

        assert await result.acount() == 0

    async def test_regular_user_sees_no_conference_assignments(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        regular_user = await User.objects.acreate_user(username=faker.user_name())
        user = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            regular_user,
        )

        assert await result.acount() == 0


@pytest.mark.django_db(transaction=True)
class TestVisibleTrackRoleAssignments:
    async def test_superuser_sees_all_track_assignments_on_active_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment_on_active = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user1,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            superuser,
        )

        assert await result.acount() == 1
        assert {a async for a in result} == {assignment_on_active}

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_role_sees_all_track_assignments_on_active_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        global_role: GlobalRole,
    ) -> None:
        global_user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=global_user, role=global_role)
        user = await User.objects.acreate_user(username=faker.user_name())
        assignment = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference, global_user
        )

        assert await result.acount() == 1
        assert {a async for a in result} == {assignment}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_track_assignments_on_active_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            user=conference_admin,
            conference=conference,
            role=conference_role,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment1 = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user1,
            role=TrackRole.REVIEWER,
        )
        assignment2 = await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user2,
            role=TrackRole.CHAIR,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            conference_admin,
        )

        assert await result.acount() == 2
        assert {a async for a in result} == {assignment1, assignment2}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_does_not_see_inactive_track_assignments(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            user=conference_admin,
            conference=conference,
            role=conference_role,
        )
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment_on_active = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user1,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            conference_admin,
        )

        assert await result.acount() == 1
        assert {a async for a in result} == {assignment_on_active}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_only_assignments_on_their_active_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment_on_track_a = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user1,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference, track_admin
        )

        # +1 for track_admin's own assignment
        assert await result.acount() == 2
        assert assignment_on_track_a in {a async for a in result}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_of_inactive_track_sees_no_assignments(
        self,
        faker: Faker,
        conference: Conference,
        track_role: TrackRole,
    ) -> None:
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=track_admin,
            role=track_role,
        )
        user = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            track_admin,
        )

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_of_both_active_and_inactive_tracks_sees_only_active(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=track_admin,
            role=track_role,
        )
        user_on_active = await User.objects.acreate_user(username=faker.user_name())
        user_on_inactive = await User.objects.acreate_user(username=faker.user_name())
        assignment_on_active = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user_on_active,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user_on_inactive,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            track_admin,
        )

        # Should see: track_admin's own assignment on active track + user_on_active
        assert await result.acount() == 2
        assert assignment_on_active in {a async for a in result}

    async def test_excludes_assignments_on_inactive_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())
        assignment_on_active = await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user1,
            role=TrackRole.REVIEWER,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user2,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            superuser,
        )

        assert await result.acount() == 1
        assert {a async for a in result} == {assignment_on_active}

    async def test_regular_user_sees_no_track_assignments(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        regular_user = await User.objects.acreate_user(username=faker.user_name())
        user = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user,
            role=TrackRole.REVIEWER,
        )

        result = await RoleAssignmentService.visible_track_role_assignments(
            conference,
            regular_user,
        )

        assert await result.acount() == 0

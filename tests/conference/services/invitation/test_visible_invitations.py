from collections.abc import Awaitable, Callable

import pytest
from asgiref.sync import sync_to_async
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import InvitationService
from app.core.models import GlobalRole, GlobalRoleAssignment, User

from .conftest import add_invitation_roles

a_add_invitation_roles = sync_to_async(add_invitation_roles)

InvitationFactory = Callable[..., Awaitable[Invitation]]


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceVisibleInvitations:
    @pytest.fixture
    def make_invitation(
        self,
        faker: Faker,
        conference: Conference,
    ) -> InvitationFactory:
        async def make_invitation() -> Invitation:
            return await Invitation.objects.acreate(
                conference=conference,
                invitee_email=faker.email(),
            )

        return make_invitation

    @pytest.fixture
    def track_a(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    @pytest.fixture
    def track_b(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    @pytest.fixture
    def track_c(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    async def test_superuser_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(conference, superuser)

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_role_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        global_role: GlobalRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=user, role=global_role)
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(conference, user)

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=conference_admin,
            role=conference_role,
        )
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(
            conference,
            conference_admin,
        )

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_invitation_with_only_their_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation, track_roles={track_a: [TrackRole.REVIEWER]}
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_mixed_track_invitation(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
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
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_ignores_inactive_other_tracks(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
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
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                inactive_track: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_other_tracks_invitation(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
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
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation, track_roles={track_b: [TrackRole.REVIEWER]}
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_invitation_with_conference_role(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_invitation_with_no_role(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=track_role,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    async def test_conference_reviewer_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            user=reviewer,
            conference=conference,
            role=ConferenceRole.REVIEWER,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, reviewer)

        assert await result.acount() == 0

    async def test_track_reviewer_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=reviewer,
            role=TrackRole.REVIEWER,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, reviewer)

        assert await result.acount() == 0

    async def test_non_admin_user_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        regular_user = await User.objects.acreate_user(username=faker.user_name())
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, regular_user)

        assert await result.acount() == 0

    async def test_multiple_administered_tracks_sees_invitation_with_one_of_tracks(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b, track_c):
            await TrackRoleAssignment.objects.acreate(
                track=track,
                user=track_admin,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    async def test_multiple_administered_tracks_sees_invitation_with_subset_of_tracks(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b, track_c):
            await TrackRoleAssignment.objects.acreate(
                track=track,
                user=track_admin,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_c: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    async def test_multiple_administered_tracks_does_not_see_invitation_with_tracks_outside_set(  # noqa: E501
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b):
            await TrackRoleAssignment.objects.acreate(
                track=track,
                user=track_admin,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_c: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    async def test_returns_exact_visible_set_with_no_duplicates(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=track_admin,
            role=TrackRole.CHAIR,
        )

        visible_invitation1 = await make_invitation()
        await a_add_invitation_roles(
            visible_invitation1,
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        visible_invitation2 = await make_invitation()
        await a_add_invitation_roles(
            visible_invitation2,
            track_roles={track_a: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

        hidden_invitation_mixed_tracks = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_mixed_tracks,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.REVIEWER],
            },
        )

        hidden_invitation_conference_role = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_conference_role,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        hidden_invitation_other_track = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_other_track,
            track_roles={track_b: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)
        result_list = [invitation async for invitation in result]

        assert len(result_list) == 2
        assert len(set(result_list)) == 2
        assert set(result_list) == {visible_invitation1, visible_invitation2}

    async def test_inactive_track_admin_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
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
            role=TrackRole.CHAIR,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={inactive_track: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

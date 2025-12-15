import pytest
from django.contrib.auth.models import AnonymousUser

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import a_update_object


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

        qs = await ConferenceService.visible_tracks(AnonymousUser())
        tracks = [track async for track in qs]

        assert tracks == [public_track]

    async def test_superuser_sees_all_tracks(
        self,
        user: User,
        conference: Conference,
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

        qs = await ConferenceService.visible_tracks(user)
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

        qs = await ConferenceService.visible_tracks(user)
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

        qs = await ConferenceService.visible_tracks(user)
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

        qs = await ConferenceService.visible_tracks(user)
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

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == [active_track]

    @pytest.mark.parametrize("track_role", TrackRole)
    async def test_member_only_track_visible_to_any_track_role(
        self,
        user: User,
        conference: Conference,
        track_role: TrackRole,
    ) -> None:
        member_only_track = await Track.objects.acreate(
            conference=conference,
            display_name="Member Only Track",
            visibility=Track.Visibility.MEMBER_ONLY,
        )
        await TrackRoleAssignment.objects.acreate(
            track=member_only_track,
            user=user,
            role=track_role,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == [member_only_track]

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_track_non_admin_role_cannot_see_admin_only_track(
        self,
        user: User,
        conference: Conference,
        non_admin_role: TrackRole,
    ) -> None:
        admin_only_track = await Track.objects.acreate(
            conference=conference,
            display_name="Admin Only Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await TrackRoleAssignment.objects.acreate(
            track=admin_only_track,
            user=user,
            role=non_admin_role,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == []

    @pytest.mark.parametrize("admin_role", TrackRole.admins())
    async def test_track_admin_can_see_admin_only_track(
        self,
        user: User,
        conference: Conference,
        admin_role: TrackRole,
    ) -> None:
        admin_only_track = await Track.objects.acreate(
            conference=conference,
            display_name="Admin Only Track",
            visibility=Track.Visibility.ADMIN_ONLY,
        )
        await TrackRoleAssignment.objects.acreate(
            track=admin_only_track,
            user=user,
            role=admin_role,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == [admin_only_track]

    async def test_user_without_role_cannot_see_member_only_track(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        await Track.objects.acreate(
            conference=conference,
            display_name="Member Only Track",
            visibility=Track.Visibility.MEMBER_ONLY,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == []

    @pytest.mark.parametrize(
        "conference_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    async def test_conference_non_admin_role_does_not_grant_member_only_track_access(
        self,
        user: User,
        conference: Conference,
        conference_role: ConferenceRole,
    ) -> None:
        await Track.objects.acreate(
            conference=conference,
            display_name="Member Only Track",
            visibility=Track.Visibility.MEMBER_ONLY,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=conference_role,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == []

    @pytest.mark.parametrize("track_role", TrackRole)
    @pytest.mark.parametrize("visibility", Track.Visibility)
    async def test_inactive_track_role_does_not_grant_track_visibility(
        self,
        user: User,
        conference: Conference,
        track_role: TrackRole,
        visibility: Track.Visibility,
    ) -> None:
        inactive_track = await Track.objects.acreate(
            conference=conference,
            display_name="Inactive Track",
            visibility=visibility,
            active=False,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user,
            role=track_role,
        )

        qs = await ConferenceService.visible_tracks(user)
        tracks = [track async for track in qs]

        assert tracks == []

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
from app.core.models import User
from tests.helpers import a_update_object


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

    async def test_global_admin_role_grants_full_visibility(
        self,
        global_admin: User,
    ) -> None:
        private = await Conference.objects.acreate(
            name="secure-conf",
            display_name="Secure",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )

        qs = await ConferenceService.visible_conferences(global_admin)
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

    async def test_inactive_track_admin_does_not_gain_visibility(
        self,
        user: User,
    ) -> None:
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
        inactive_track = await Track.objects.acreate(
            conference=target,
            display_name="Inactive Track",
            active=False,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs.order_by("name")]

        assert conferences == []

    @pytest.mark.parametrize(
        "track_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_inactive_track_non_admin_role_does_not_grant_conference_visibility(
        self,
        user: User,
        track_role: TrackRole,
    ) -> None:
        member_only = await Conference.objects.acreate(
            name="member-only-conf",
            display_name="Member Only",
            visibility=Conference.Visibility.MEMBER_ONLY,
        )
        inactive_track = await Track.objects.acreate(
            conference=member_only,
            display_name="Inactive Track",
            active=False,
        )
        await TrackRoleAssignment.objects.acreate(
            track=inactive_track,
            user=user,
            role=track_role,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs]

        assert conferences == []

    @pytest.mark.parametrize("conference_role", ConferenceRole)
    async def test_member_only_conference_visible_to_any_conference_role(
        self,
        user: User,
        conference_role: ConferenceRole,
    ) -> None:
        member_only = await Conference.objects.acreate(
            name="member-only-conf",
            display_name="Member Only",
            visibility=Conference.Visibility.MEMBER_ONLY,
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=member_only,
            user=user,
            role=conference_role,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs]

        assert conferences == [member_only]

    @pytest.mark.parametrize("track_role", TrackRole)
    async def test_member_only_conference_visible_to_any_track_role(
        self,
        user: User,
        track_role: TrackRole,
    ) -> None:
        member_only = await Conference.objects.acreate(
            name="member-only-conf",
            display_name="Member Only",
            visibility=Conference.Visibility.MEMBER_ONLY,
        )
        track = await Track.objects.acreate(
            conference=member_only,
            display_name="Track",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=track_role,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs]

        assert conferences == [member_only]

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_track_non_admin_role_does_not_unlock_admin_only_conference(
        self,
        user: User,
        non_admin_role: TrackRole,
    ) -> None:
        admin_only = await Conference.objects.acreate(
            name="admin-only-conf",
            display_name="Admin Only",
            visibility=Conference.Visibility.ADMIN_ONLY,
        )
        track = await Track.objects.acreate(
            conference=admin_only,
            display_name="Track",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=non_admin_role,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs]

        assert conferences == []

    async def test_user_without_role_cannot_see_member_only_conference(
        self,
        user: User,
    ) -> None:
        await Conference.objects.acreate(
            name="member-only-conf",
            display_name="Member Only",
            visibility=Conference.Visibility.MEMBER_ONLY,
        )

        qs = await ConferenceService.visible_conferences(user)
        conferences = [conf async for conf in qs]

        assert conferences == []

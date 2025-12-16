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
from app.conference.services import ConferenceAccessService
from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def other_conference(faker: Faker) -> Conference:
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


@pytest.fixture
def track_other_conference(faker: Faker, other_conference: Conference) -> Track:
    return Track.objects.create(
        conference=other_conference,
        display_name=faker.word(),
    )


@pytest.mark.django_db(transaction=True)
class TestConferenceAccessServiceContext:
    async def test_superuser_has_full_access(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        user = await User.objects.acreate_superuser(username=faker.user_name())

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.global_privileged is True
        assert ctx.conference_admin is False
        assert ctx.has_full_conference_scope is True
        assert ctx.administered_track_ids == frozenset()
        assert ctx.can_admin_track(track_a) is True

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_roles_have_full_access(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        global_role: GlobalRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=user, role=global_role)

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.global_privileged is True
        assert ctx.conference_admin is False
        assert ctx.has_full_conference_scope is True
        assert ctx.can_admin_track(track_a) is True

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admins_have_full_access(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        conference_role: ConferenceRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=conference_role,
        )

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.global_privileged is False
        assert ctx.conference_admin is True
        assert ctx.has_full_conference_scope is True
        assert ctx.can_admin_track(track_a) is True

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admins_limited_to_their_tracks(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        track_role: TrackRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            track=track_a,
            user=user,
            role=track_role,
        )

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.global_privileged is False
        assert ctx.conference_admin is False
        assert ctx.has_full_conference_scope is False
        assert ctx.administered_track_ids == frozenset([track_a.pk])
        assert ctx.can_admin_track(track_a) is True
        assert ctx.can_admin_track(track_b) is False

    async def test_non_admin_cannot_admin_any_track(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.global_privileged is False
        assert ctx.conference_admin is False
        assert ctx.has_full_conference_scope is False
        assert ctx.administered_track_ids == frozenset()
        assert ctx.can_admin_track(track_a) is False

    async def test_cannot_admin_tracks_from_other_conferences(
        self,
        faker: Faker,
        conference: Conference,
        track_a: Track,
        track_other_conference: Track,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        ctx = await ConferenceAccessService.context(conference=conference, user=user)

        assert ctx.can_admin_track(track_a) is True
        assert ctx.can_admin_track(track_other_conference) is False

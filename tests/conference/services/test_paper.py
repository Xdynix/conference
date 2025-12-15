import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import a_update_object


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
class TestPaperServiceVisiblePapers:
    async def test_superuser_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    async def test_global_admin_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.ADMIN)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    async def test_global_read_all_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.READ_ALL)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        conference_role: ConferenceRole,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=conference_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_only_papers_in_their_track(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
        track_role: TrackRole,
    ) -> None:
        other_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        paper_in_track = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Paper in Track",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=other_track,
            owner=user,
            code="PAPER-002",
            title="Paper in Other Track",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=track_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper_in_track]

    async def test_track_admin_sees_papers_from_multiple_administered_tracks(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        track_c = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        paper_a = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-A",
            title="Paper A",
        )
        paper_b = await Paper.objects.acreate(
            conference=conference,
            track=track_b,
            owner=user,
            code="PAPER-B",
            title="Paper B",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=track_c,
            owner=user,
            code="PAPER-C",
            title="Paper C",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user,
            role=TrackRole.SECRETARY,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs.order_by("code")]

        assert papers == [paper_a, paper_b]

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_track_non_admin_role_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        non_admin_role: TrackRole,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=non_admin_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    async def test_conference_non_admin_role_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        non_admin_role: ConferenceRole,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=non_admin_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_user_without_roles_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_excludes_deleted_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        active_paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="ACTIVE-001",
            title="Active Paper",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="DELETED-001",
            title="Deleted Paper",
            delete_time=timezone.now(),
        )
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [active_paper]

    async def test_inactive_track_does_not_grant_visibility(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(track, active=False)
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_returns_empty_when_no_papers(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

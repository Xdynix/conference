import pytest
from django.contrib.auth.models import AnonymousUser
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService
from app.conference.services.conference import ConferenceNameConflict, TrackData
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import a_update_object, update_object


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.mark.django_db
class TestConferenceServiceCreateConference:
    def test_happy_path(self, faker: Faker) -> None:
        name = faker.slug()
        display_name = faker.sentence()
        visibility = Conference.Visibility.PUBLIC

        conference = ConferenceService.create_conference(
            name=name,
            display_name=display_name,
            visibility=visibility,
            keywords=[],
            keyword_sets=[],
            tracks=[],
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert conference.name == db_conference.name == name
        assert conference.display_name == db_conference.display_name == display_name
        assert conference.visibility == db_conference.visibility == visibility
        assert not db_conference.keywords.exists()
        assert db_conference.tracks.count() == 0

    def test_creates_conference_with_keywords(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="machine-learning")
        keyword2 = Keyword.objects.create(text="ai")

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1, keyword2],
            keyword_sets=[],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2}

    def test_creates_conference_with_keyword_sets(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="nlp")
        keyword2 = Keyword.objects.create(text="deep-learning")
        keyword3 = Keyword.objects.create(text="computer-vision")

        keyword_set1 = KeywordSet.objects.create(name="ml-topics")
        keyword_set1.keywords.set([keyword1, keyword2])

        keyword_set2 = KeywordSet.objects.create(name="vision")
        keyword_set2.keywords.set([keyword3])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[],
            keyword_sets=[keyword_set1, keyword_set2],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_combines_keywords_and_keyword_sets(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="robotics")
        keyword2 = Keyword.objects.create(text="automation")
        keyword3 = Keyword.objects.create(text="control-systems")

        keyword_set = KeywordSet.objects.create(name="robotics-topics")
        keyword_set.keywords.set([keyword2, keyword3])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_deduplicates_keywords_from_multiple_sources(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="security")
        keyword2 = Keyword.objects.create(text="cryptography")

        keyword_set = KeywordSet.objects.create(name="security-topics")
        keyword_set.keywords.set([keyword1, keyword2])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2}

    def test_creates_conference_with_tracks(self, faker: Faker) -> None:
        tracks = [
            TrackData(display_name=display_name, visibility=visibility)
            for display_name, visibility in [
                ("Track A", Track.Visibility.PUBLIC),
                ("Track B", Track.Visibility.ADMIN_ONLY),
                ("Track C", Track.Visibility.PUBLIC),
            ]
        ]

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
            keywords=[],
            keyword_sets=[],
            tracks=tracks,
        )

        db_tracks = list(
            Conference.objects.get(pk=conference.pk).tracks.order_by("ordering")
        )
        assert len(db_tracks) == 3
        assert db_tracks[0].display_name == "Track A"
        assert db_tracks[0].ordering == 0
        assert db_tracks[0].visibility == Track.Visibility.PUBLIC
        assert db_tracks[1].display_name == "Track B"
        assert db_tracks[1].ordering == 1
        assert db_tracks[1].visibility == Track.Visibility.ADMIN_ONLY
        assert db_tracks[2].display_name == "Track C"
        assert db_tracks[2].ordering == 2
        assert db_tracks[2].visibility == Track.Visibility.PUBLIC

    def test_raises_conference_name_conflict_for_duplicate_name(
        self, faker: Faker
    ) -> None:
        existing_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        with pytest.raises(ConferenceNameConflict):
            ConferenceService.create_conference(
                name=existing_conference.name,
                display_name=faker.sentence(),
                visibility=Conference.Visibility.PUBLIC,
                keywords=[],
                keyword_sets=[],
                tracks=[],
            )

        assert Conference.objects.filter(name=existing_conference.name).count() == 1


@pytest.mark.django_db
class TestConferenceServiceUpdateConference:
    def test_update_display_name(self, conference: Conference) -> None:
        updated = ConferenceService.update_conference(
            name=conference.name,
            display_name="New Display Name",
        )

        db_updated = Conference.objects.get(pk=conference.pk)
        assert updated.display_name == db_updated.display_name == "New Display Name"

    def test_update_visibility(self, conference: Conference) -> None:
        update_object(conference, visibility=Conference.Visibility.ADMIN_ONLY)

        updated = ConferenceService.update_conference(
            name=conference.name,
            visibility=Conference.Visibility.PUBLIC,
        )

        db_updated = Conference.objects.get(pk=conference.pk)
        assert (
            updated.visibility == db_updated.visibility == Conference.Visibility.PUBLIC
        )

    def test_update_keywords(self, conference: Conference) -> None:
        keyword1 = Keyword.objects.create(text="python")
        keyword2 = Keyword.objects.create(text="django")
        keyword3 = Keyword.objects.create(text="rust")
        conference.keywords.set([keyword1, keyword2])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[keyword3],
        )

        assert set(updated.keywords.all()) == {keyword3}

    def test_update_keyword_sets(self, conference: Conference) -> None:
        keyword1 = Keyword.objects.create(text="backend")
        keyword2 = Keyword.objects.create(text="frontend")
        keyword_set = KeywordSet.objects.create(name="web-dev")
        keyword_set.keywords.set([keyword1, keyword2])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keyword_sets=[keyword_set],
        )

        assert set(updated.keywords.all()) == {keyword1, keyword2}

    def test_update_combines_keywords_and_keyword_sets(
        self,
        conference: Conference,
    ) -> None:
        keyword1 = Keyword.objects.create(text="api")
        keyword2 = Keyword.objects.create(text="microservices")
        keyword3 = Keyword.objects.create(text="cloud")
        keyword_set = KeywordSet.objects.create(name="architecture")
        keyword_set.keywords.set([keyword2, keyword3])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
        )

        assert set(updated.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_update_clears_keywords_with_empty_list(
        self,
        conference: Conference,
    ) -> None:
        keyword = Keyword.objects.create(text="docker")
        conference.keywords.set([keyword])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[],
        )

        assert not updated.keywords.exists()

    def test_update_none_keywords_preserves_existing(
        self,
        conference: Conference,
    ) -> None:
        keyword = Keyword.objects.create(text="kubernetes")
        conference.keywords.set([keyword])

        updated = ConferenceService.update_conference(
            name=conference.name,
            display_name="Updated Name",
        )

        assert updated.display_name == "Updated Name"
        assert set(updated.keywords.all()) == {keyword}

    def test_no_op_when_no_fields_provided(self, conference: Conference) -> None:
        update_object(conference, display_name="Original")
        original_update_time = conference.update_time

        ConferenceService.update_conference(name=conference.name)

        conference.refresh_from_db()
        assert conference.display_name == "Original"
        assert conference.update_time == original_update_time

    def test_raises_does_not_exist_for_unknown_conference(self) -> None:
        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.update_conference(
                name="nonexistent-conf",
                display_name="Test",
            )

    def test_raises_does_not_exist_for_inactive_conference(
        self,
        conference: Conference,
    ) -> None:
        update_object(
            conference,
            display_name="Original",
            active=False,
        )
        original_update_time = conference.update_time

        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.update_conference(
                name=conference.name,
                display_name="Updated",
            )

        conference.refresh_from_db()
        assert conference.display_name == "Original"
        assert conference.update_time == original_update_time


@pytest.mark.django_db
class TestConferenceServiceDeactivateConference:
    def test_happy_path(self, conference: Conference) -> None:
        deactivated = ConferenceService.deactivate_conference(name=conference.name)

        db_deactivated = Conference.objects.get(pk=deactivated.pk)
        assert deactivated.active == db_deactivated.active is False

    def test_raises_does_not_exist_for_unknown_conference(self) -> None:
        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.deactivate_conference(name="missing-conf")

    def test_raises_does_not_exist_for_inactive_conference(
        self,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.deactivate_conference(name=conference.name)


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

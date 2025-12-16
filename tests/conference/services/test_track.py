from itertools import pairwise

import pytest
from faker import Faker
from ulid import ULID

from app.conference.models import Conference, Track
from app.conference.services import TrackService
from tests.helpers import a_update_object, update_object


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track(conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name="Track",
    )


@pytest.mark.django_db
class TestTrackServiceCreateTask:
    def test_happy_path(self, conference: Conference) -> None:
        existing = Track.objects.create(
            conference=conference,
            display_name="Existing",
        )

        new = TrackService.create_track(
            conference_name=conference.name,
            display_name="New",
            visibility=Track.Visibility.PUBLIC,
        )

        db_new = Track.objects.get(pk=new.pk)
        assert new.conference == db_new.conference == conference
        assert new.display_name == db_new.display_name == "New"
        assert new.ordering == db_new.ordering > existing.ordering
        assert new.visibility == db_new.visibility == Track.Visibility.PUBLIC

        assert (existing, new) == tuple(conference.tracks.all())

    def test_inactive_conference(self, conference: Conference) -> None:
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            TrackService.create_track(
                conference_name=conference.name,
                display_name="New",
                visibility=Track.Visibility.PUBLIC,
            )

        assert not conference.tracks.filter(display_name="New").exists()


@pytest.mark.django_db(transaction=True)
class TestTrackServiceUpdateTask:
    async def test_happy_path(self, track: Track) -> None:
        await a_update_object(
            track,
            display_name="Old",
            visibility=Track.Visibility.ADMIN_ONLY,
            submissions_enabled=False,
        )

        updated = await TrackService.update_track(
            conference_name=track.conference.name,
            track_uid=track.uid,
            display_name="New",
            visibility=Track.Visibility.PUBLIC,
            submissions_enabled=True,
        )

        db_updated = await Track.objects.aget(pk=updated.pk)
        assert updated.display_name == db_updated.display_name == "New"
        assert updated.visibility == db_updated.visibility == Track.Visibility.PUBLIC
        assert updated.submissions_enabled is db_updated.submissions_enabled is True

    async def test_inactive_conference(self, track: Track) -> None:
        await a_update_object(track.conference, active=False)

        with pytest.raises(Track.DoesNotExist):
            await TrackService.update_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
                display_name="New",
            )

        await track.arefresh_from_db()
        assert track.display_name == "Track"

    async def test_inactive_track(self, track: Track) -> None:
        await a_update_object(
            track,
            display_name="Inactive",
            active=False,
        )

        with pytest.raises(Track.DoesNotExist):
            await TrackService.update_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
                display_name="New",
            )

        await track.arefresh_from_db()
        assert track.display_name == "Inactive"

    async def test_mismatch_conference(self) -> None:
        conf1 = await Conference.objects.acreate(name="conf-1", display_name="conf-1")
        conf2 = await Conference.objects.acreate(name="conf-2", display_name="conf-2")
        track2 = await Track.objects.acreate(conference=conf2, display_name="track-2")

        with pytest.raises(Track.DoesNotExist):
            await TrackService.update_track(
                conference_name=conf1.name,
                track_uid=track2.uid,
                display_name="New",
            )

        await track2.arefresh_from_db()
        assert track2.display_name == "track-2"


@pytest.mark.django_db
class TestTrackServiceDeactivateTask:
    def test_happy_path(self, track: Track) -> None:
        deactivated = TrackService.deactivate_track(
            conference_name=track.conference.name,
            track_uid=track.uid,
        )

        db_deactivated = Track.objects.get(pk=deactivated.pk)
        assert deactivated.active == db_deactivated.active is False

    def test_inactive_conference(self, track: Track) -> None:
        update_object(track.conference, active=False)

        with pytest.raises(Track.DoesNotExist):
            TrackService.deactivate_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
            )

        track.refresh_from_db()
        assert track.active is True

    def test_inactive_track(self, track: Track) -> None:
        update_object(track, active=False)

        with pytest.raises(Track.DoesNotExist):
            TrackService.deactivate_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
            )

        track.refresh_from_db()
        assert track.active is False

    def test_mismatch_conference(self) -> None:
        conf1 = Conference.objects.create(name="conf-1", display_name="conf-1")
        conf2 = Conference.objects.create(name="conf-2", display_name="conf-2")
        track2 = Track.objects.create(conference=conf2, display_name="track-2")

        with pytest.raises(Track.DoesNotExist):
            TrackService.deactivate_track(
                conference_name=conf1.name,
                track_uid=track2.uid,
            )

        track2.refresh_from_db()
        assert track2.active is True


@pytest.mark.django_db
class TestTrackServiceMoveTrack:
    @pytest.fixture
    def tracks(self, conference: Conference) -> tuple[Track, ...]:
        return tuple(
            Track.objects.create(
                conference=conference,
                display_name=name,
                ordering=idx,
                visibility=Track.Visibility.PUBLIC,
            )
            for idx, name in enumerate(["Alpha", "Beta", "Gamma"])
        )

    @classmethod
    def assert_ordering(cls, *tracks: Track) -> None:
        for track in tracks:
            track.refresh_from_db()
        for a, b in pairwise(tracks):
            assert a.ordering < b.ordering

    def test_happy_path(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        third_moved = TrackService.move_track(
            conference_name=conference.name,
            track_uid=third.uid,
            after_track_uid=first.uid,
        )

        db_third_moved = Track.objects.get(pk=third_moved.pk)
        assert third_moved.ordering == db_third_moved.ordering

        self.assert_ordering(first, third, second)

    def test_move_to_head(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        TrackService.move_track(
            conference_name=conference.name,
            track_uid=third.uid,
            after_track_uid=None,
        )

        self.assert_ordering(third, first, second)

    def test_inactive_conference(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            TrackService.move_track(
                conference_name=conference.name,
                track_uid=third.uid,
                after_track_uid=first.uid,
            )

        self.assert_ordering(first, second, third)

    def test_inactive_track(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        update_object(third, active=False)

        with pytest.raises(Track.DoesNotExist):
            TrackService.move_track(
                conference_name=conference.name,
                track_uid=third.uid,
                after_track_uid=first.uid,
            )

        self.assert_ordering(first, second, third)

    def test_mismatch_conference(self) -> None:
        conf1 = Conference.objects.create(name="conf-1", display_name="conf-1")
        conf2 = Conference.objects.create(name="conf-2", display_name="conf-2")
        track2 = Track.objects.create(conference=conf2, display_name="track-2")

        with pytest.raises(Track.DoesNotExist):
            TrackService.move_track(
                conference_name=conf1.name,
                track_uid=track2.uid,
                after_track_uid=None,
            )

    def test_move_after_self(self, track: Track) -> None:
        with pytest.raises(ValueError, match=r"Track cannot be moved after itself."):
            TrackService.move_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
                after_track_uid=track.uid,
            )

    def test_inactive_target(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        update_object(first, active=False)

        with pytest.raises(ValueError, match=r"Target track does not exist."):
            TrackService.move_track(
                conference_name=conference.name,
                track_uid=third.uid,
                after_track_uid=first.uid,
            )

        self.assert_ordering(first, second, third)

    def test_not_exist_target(self, track: Track) -> None:
        with pytest.raises(ValueError, match=r"Target track does not exist."):
            TrackService.move_track(
                conference_name=track.conference.name,
                track_uid=track.uid,
                after_track_uid=ULID(),
            )

import pytest
from ulid import ULID

from app.conference.models import Conference, Track, TrackVisibility
from app.conference.services import TrackService
from tests.helpers import a_update_object, update_object


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
            visibility=TrackVisibility.PUBLIC,
        )

        db_new = Track.objects.get(pk=new.pk)
        assert new.conference == db_new.conference == conference
        assert new.display_name == db_new.display_name == "New"
        assert new.ordering == db_new.ordering > existing.ordering
        assert new.visibility == db_new.visibility == TrackVisibility.PUBLIC

        assert (existing, new) == tuple(conference.tracks.all())

    def test_inactive_conference(self, conference: Conference) -> None:
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            TrackService.create_track(
                conference_name=conference.name,
                display_name="New",
                visibility=TrackVisibility.PUBLIC,
            )

        assert not conference.tracks.filter(display_name="New").exists()


@pytest.mark.django_db(transaction=True)
class TestTrackServiceUpdateTask:
    async def test_happy_path(self, track: Track) -> None:
        await a_update_object(
            track,
            display_name="Old",
            visibility=TrackVisibility.ADMIN_ONLY,
            submissions_enabled=False,
        )

        updated = await TrackService.update_track(
            conference_name=track.conference.name,
            track_uid=track.uid,
            display_name="New",
            visibility=TrackVisibility.PUBLIC,
            submissions_enabled=True,
        )

        db_updated = await Track.objects.aget(pk=updated.pk)
        assert updated.display_name == db_updated.display_name == "New"
        assert updated.visibility == db_updated.visibility == TrackVisibility.PUBLIC
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
class TestTrackServiceReorderTracks:
    @pytest.fixture
    def tracks(self, conference: Conference) -> tuple[Track, ...]:
        return tuple(
            Track.objects.create(
                conference=conference,
                display_name=name,
                ordering=idx,
                visibility=TrackVisibility.PUBLIC,
            )
            for idx, name in enumerate(["Alpha", "Beta", "Gamma"])
        )

    def test_happy_path(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        result = TrackService.reorder_tracks(
            conference_name=conference.name,
            track_uids=[third.uid, first.uid, second.uid],
        )

        assert result == conference

        for track in tracks:
            track.refresh_from_db()
        assert third.ordering == 0
        assert first.ordering == 1
        assert second.ordering == 2

    def test_reverse_order(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        TrackService.reorder_tracks(
            conference_name=conference.name,
            track_uids=[third.uid, second.uid, first.uid],
        )

        for track in tracks:
            track.refresh_from_db()
        assert third.ordering == 0
        assert second.ordering == 1
        assert first.ordering == 2

    def test_same_order_no_updates(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        original_update_times = [t.update_time for t in tracks]

        TrackService.reorder_tracks(
            conference_name=conference.name,
            track_uids=[first.uid, second.uid, third.uid],
        )

        for track, original_time in zip(tracks, original_update_times, strict=True):
            track.refresh_from_db()
            assert track.update_time == original_time

    def test_inactive_conference(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            TrackService.reorder_tracks(
                conference_name=conference.name,
                track_uids=[third.uid, first.uid, second.uid],
            )

        for track in tracks:
            track.refresh_from_db()
        assert first.ordering == 0
        assert second.ordering == 1
        assert third.ordering == 2

    def test_duplicate_uids(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        with pytest.raises(ValueError, match=r"Duplicate UIDs"):
            TrackService.reorder_tracks(
                conference_name=conference.name,
                track_uids=[first.uid, first.uid, second.uid, third.uid],
            )

        for track in tracks:
            track.refresh_from_db()
        assert first.ordering == 0
        assert second.ordering == 1
        assert third.ordering == 2

    def test_missing_uids(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks

        with pytest.raises(ValueError, match=r"Missing UIDs"):
            TrackService.reorder_tracks(
                conference_name=conference.name,
                track_uids=[first.uid, second.uid],
            )

        for track in tracks:
            track.refresh_from_db()
        assert first.ordering == 0
        assert second.ordering == 1
        assert third.ordering == 2

    def test_invalid_uids(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        unknown_uid = ULID()

        with pytest.raises(ValueError, match=r"Invalid UIDs"):
            TrackService.reorder_tracks(
                conference_name=conference.name,
                track_uids=[first.uid, second.uid, third.uid, unknown_uid],
            )

        for track in tracks:
            track.refresh_from_db()
        assert first.ordering == 0
        assert second.ordering == 1
        assert third.ordering == 2

    def test_excludes_inactive_tracks(
        self,
        conference: Conference,
        tracks: tuple[Track, ...],
    ) -> None:
        first, second, third = tracks
        update_object(second, active=False)

        TrackService.reorder_tracks(
            conference_name=conference.name,
            track_uids=[third.uid, first.uid],
        )

        for track in tracks:
            track.refresh_from_db()
        assert third.ordering == 0
        assert first.ordering == 1
        assert second.ordering == 1

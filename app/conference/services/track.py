from typing import Any

from django.utils.translation import gettext as _
from ulid import ULID

from app.conference.models import Conference, Track, TrackVisibility
from app.infra.models import Mutex


class TrackService:
    @classmethod
    def create_track(
        cls,
        *,
        conference_name: str,
        display_name: str,
        visibility: TrackVisibility,
    ) -> Track:
        """Create a new track and append it to the end of the conference's track list.

        Returns:
            The newly created track instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        with Mutex.lock_in_transaction(conference_name, namespace="conference_tracks"):
            conference = Conference.objects.active().get(name=conference_name)
            last_ordering = (
                conference.tracks.order_by("-ordering")
                .values_list("ordering", flat=True)
                .first()
            )
            next_ordering = 0 if last_ordering is None else last_ordering + 1
            track = Track.objects.create(
                conference=conference,
                display_name=display_name,
                ordering=next_ordering,
                visibility=visibility,
            )
            return Track.objects.select_related("conference").get(pk=track.pk)

    @classmethod
    async def update_track(
        cls,
        *,
        conference_name: str,
        track_uid: ULID,
        **updates: Any,
    ) -> Track:
        """Update a track.

        Returns:
            The updated track instance.

        Raises:
            Track.DoesNotExist: If the track is not found.
        """
        # No transaction needed: `save(update_fields=[...])` generates a single atomic
        # UPDATE query that sets specific fields directly without reading current
        # values, so there's no read-modify-write cycle or risk of lost updates.
        track = await (
            Track.objects.active()
            .filter(conference__name=conference_name)
            .select_related("conference")
            .aget(uid=track_uid)
        )
        if updates:
            for attr, value in updates.items():
                setattr(track, attr, value)
            await track.asave(update_fields=[*updates, "update_time"])
        return track

    @classmethod
    def deactivate_track(
        cls,
        *,
        conference_name: str,
        track_uid: ULID,
    ) -> Track:
        """Deactivate a track.

        Returns:
            The deactivated track instance.

        Raises:
            Track.DoesNotExist: If the track is not found.
        """
        with Mutex.lock_in_transaction(conference_name, namespace="conference_tracks"):
            track = (
                Track.objects.active()
                .filter(conference__name=conference_name)
                .select_related("conference")
                .get(uid=track_uid)
            )
            track.active = False
            track.save(update_fields=["active", "update_time"])
            return track

    @classmethod
    def reorder_tracks(
        cls,
        *,
        conference_name: str,
        track_uids: list[ULID],
    ) -> Conference:
        """Reorder tracks within a conference.

        The order of UIDs in the list determines the new ordering. All active tracks
        must be included exactly once.

        Returns:
            The conference instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
            ValueError: If the list contains duplicates, missing active tracks, or
                invalid UIDs.
        """
        with Mutex.lock_in_transaction(conference_name, namespace="conference_tracks"):
            conference = Conference.objects.active().get(name=conference_name)
            active_tracks = {t.uid: t for t in conference.tracks.active()}

            payload_uids = set(track_uids)
            if len(track_uids) != len(payload_uids):
                seen: set[ULID] = set()
                duplicates: set[ULID] = set()
                for uid in track_uids:
                    if uid in seen:
                        duplicates.add(uid)
                    seen.add(uid)
                raise ValueError(
                    _("Duplicate UIDs: {uids}.").format(
                        uids=", ".join(str(uid) for uid in sorted(duplicates))
                    )
                )

            existing_uids = set(active_tracks)
            missing_uids = existing_uids - payload_uids
            if missing_uids:
                raise ValueError(
                    _("Missing UIDs: {uids}.").format(
                        uids=", ".join(str(uid) for uid in sorted(missing_uids))
                    )
                )

            invalid_uids = payload_uids - existing_uids
            if invalid_uids:
                raise ValueError(
                    _("Invalid UIDs: {uids}.").format(
                        uids=", ".join(str(uid) for uid in sorted(invalid_uids))
                    )
                )

            for ordering, uid in enumerate(track_uids):
                track = active_tracks[uid]
                if track.ordering != ordering:
                    track.ordering = ordering
                    track.save(update_fields=["ordering", "update_time"])

            return conference

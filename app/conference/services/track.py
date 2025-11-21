from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _
from ulid import ULID

from app.conference.models import Conference, Track


class TrackService:
    @classmethod
    @transaction.atomic
    def create_track(
        cls,
        *,
        conference_name: str,
        display_name: str,
        visibility: Track.Visibility,
    ) -> Track:
        """Create a new track and append it to the end of the conference's track list.

        Returns:
            The newly created track instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        conference = (
            Conference.objects.active()
            # Lock the conference row to prevent race conditions when calculating the
            # next ordering value, even though we don't update the conference itself.
            .select_for_update()
            .get(name=conference_name)
        )
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
    @transaction.atomic
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
        track = (
            Track.objects.active()
            .filter(conference__name=conference_name)
            .select_for_update()
            .select_related("conference")
            .get(uid=track_uid)
        )
        track.active = False
        track.save(update_fields=["active", "update_time"])
        return track

    @classmethod
    @transaction.atomic
    def move_track(
        cls,
        *,
        conference_name: str,
        track_uid: ULID,
        after_track_uid: ULID | None,
    ) -> Track:
        """Move a track to a new position within its conference.

        Places the track after the specified track, or at the beginning if no target is
        specified.

        Returns:
            The moved track instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
            Track.DoesNotExist: If the track is not found.
            ValueError: If the track is being moved after itself or if the target track
                does not exist.
        """
        if after_track_uid == track_uid:
            raise ValueError(_("Track cannot be moved after itself."))

        conference = (
            Conference.objects.active()
            # Lock the conference row to prevent race conditions when calculating the
            # new ordering values, even though we don't update the conference itself.
            .select_for_update()
            .get(name=conference_name)
        )

        track = (
            conference.tracks.active().select_related("conference").get(uid=track_uid)
        )

        # Include inactive tracks in reordering to maintain consistent ordering values
        # across the entire track history. This simplifies the logic and preserves
        # ordering continuity if tracks are reactivated later.
        conference_tracks = list(conference.tracks.exclude(pk=track.pk))

        if after_track_uid is None:
            conference_tracks.insert(0, track)
        else:
            try:
                target_index = next(
                    idx
                    for idx, track_obj in enumerate(conference_tracks)
                    if track_obj.active and track_obj.uid == after_track_uid
                )
            except StopIteration as exc:
                raise ValueError(_("Target track does not exist.")) from exc
            conference_tracks.insert(target_index + 1, track)

        for ordering, track_obj in enumerate(conference_tracks):
            if track_obj.ordering != ordering:
                track_obj.ordering = ordering
                track_obj.save(update_fields=["ordering", "update_time"])

        return track

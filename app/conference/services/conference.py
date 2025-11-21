from collections import defaultdict
from collections.abc import Collection
from typing import TypedDict

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from app.conference.models import (
    Conference,
    ConferenceRole,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
)
from app.core.models import GlobalRole, User


class ConferenceNameConflict(Exception):
    pass


class TrackData(TypedDict):
    display_name: str
    visibility: Track.Visibility


class ConferenceService:
    @classmethod
    @transaction.atomic
    def create_conference(
        cls,
        *,
        name: str,
        display_name: str,
        visibility: Conference.Visibility,
        keywords: Collection[Keyword],
        keyword_sets: Collection[KeywordSet],
        tracks: Collection[TrackData],
    ) -> Conference:
        """Creates a new conference with associated keywords and tracks.

        Returns:
            The newly created conference instance.

        Raises:
            ConferenceNameConflict: If a conference with that name already exists.
        """
        try:
            conference = Conference.objects.create(
                name=name,
                display_name=display_name,
                visibility=visibility,
            )
        except IntegrityError as exc:
            raise ConferenceNameConflict from exc

        assigned_keywords: set[Keyword] = set(keywords)
        for keyword_set in keyword_sets:
            assigned_keywords.update(keyword_set.keywords.all())
        if assigned_keywords:
            conference.keywords.set(assigned_keywords)

        track_objects = [
            Track(
                conference=conference,
                display_name=track["display_name"],
                ordering=idx,
                visibility=track["visibility"],
            )
            for idx, track in enumerate(tracks)
        ]
        if track_objects:
            Track.objects.bulk_create(track_objects)

        return conference

    @classmethod
    @transaction.atomic
    def update_conference(
        cls,
        *,
        name: str,
        display_name: str | None = None,
        visibility: Conference.Visibility | None = None,
        keywords: Collection[Keyword] | None = None,
        keyword_sets: Collection[KeywordSet] | None = None,
    ) -> Conference:
        """Updates a conference's attributes.

        Returns:
            The updated conference instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        conference = Conference.objects.active().select_for_update().get(name=name)

        update_fields: list[str] = []

        if display_name is not None:
            conference.display_name = display_name
            update_fields.append("display_name")

        if visibility is not None:
            conference.visibility = visibility
            update_fields.append("visibility")

        keywords_provided = keywords is not None
        keyword_sets_provided = keyword_sets is not None
        keywords_updated = keywords_provided or keyword_sets_provided
        if keywords_updated:
            assigned_keywords: set[Keyword] = set()
            assigned_keywords.update(keywords or [])
            for keyword_set in keyword_sets or []:
                assigned_keywords.update(keyword_set.keywords.all())
            conference.keywords.set(assigned_keywords)

        if update_fields or keywords_updated:
            conference.save(update_fields=[*update_fields, "update_time"])

        return conference

    @classmethod
    @transaction.atomic
    def deactivate_conference(cls, *, name: str) -> Conference:
        """Deactivates a conference.

        Returns:
            The deactivated conference instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        conference = Conference.objects.active().select_for_update().get(name=name)
        conference.active = False
        conference.save(update_fields=["active", "update_time"])
        return conference

    @classmethod
    async def visible_conferences(
        cls,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Conference]:
        """Return the queryset of active conferences visible to ``user``.

        The queryset includes:

        - all public conferences;
        - all conferences when the user is a superuser or holds any ``global_readable``
          role;
        - private conferences where the user is a conference admin; and
        - private conferences where the user is an admin on at least one of the
          conference's tracks.
        """
        conferences = Conference.objects.active()

        if not user.is_authenticated:
            return conferences.filter(visibility=Conference.Visibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return conferences

        is_public = Q(visibility=Conference.Visibility.PUBLIC)
        is_conference_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            track__role_assignment__user=user,
            track__role_assignment__role__in=TrackRole.admins(),
        )
        return conferences.filter(
            is_public | is_conference_admin | is_track_admin
        ).distinct()

    @classmethod
    async def visible_tracks(
        cls,
        user: User | AnonymousUser,
        conferences: Collection[Conference] | QuerySet[Conference],
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Track]:
        """Return the queryset of tracks within ``conferences`` visible to ``user``.

        The queryset includes:

        - all public tracks;
        - all tracks when the user is a superuser or holds any ``global_readable`` role;
        - private tracks whose parent conference the user administers; and
        - private tracks where the user has a track-admin role.
        """
        tracks = Track.objects.active().filter(conference__in=conferences)

        if not user.is_authenticated:
            return tracks.filter(visibility=Track.Visibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return tracks

        is_public = Q(visibility=Track.Visibility.PUBLIC)
        is_conference_admin = Q(
            conference__role_assignment__user=user,
            conference__role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=TrackRole.admins(),
        )
        return tracks.filter(
            is_public | is_conference_admin | is_track_admin
        ).distinct()

    @classmethod
    async def prefetch_tracks(
        cls,
        *conferences: Conference,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> Collection[Conference]:
        """Attach track lists to conferences according to ``visible_tracks`` rules."""
        tracks = await cls.visible_tracks(
            user,
            conferences,
            global_readable=global_readable,
        )

        conference_tracks: dict[int, list[Track]] = defaultdict(list)
        async for track in tracks:
            conference_tracks[track.conference_id].append(track)

        for conference in conferences:
            conference.prefetched_tracks = conference_tracks[conference.id]

        return conferences

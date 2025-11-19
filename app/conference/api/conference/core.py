from collections import defaultdict
from collections.abc import Collection
from http import HTTPStatus

from django.contrib.auth.models import AnonymousUser
from django.db.models import Q, QuerySet
from django.utils.translation import gettext as _
from ninja import Router
from ninja.errors import HttpError

from app.conference.models import (
    Conference,
    ConferenceRole,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
)
from app.core.models import GlobalRole, User

router = Router(tags=["Conference"], exclude_none=True)


async def visible_conferences(
    user: User | AnonymousUser,
    global_readable: Collection[GlobalRole] = (GlobalRole.ADMIN, GlobalRole.READ_ALL),
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
    conferences = Conference.objects.filter(active=True)

    if not user.is_authenticated:
        return conferences.filter(visibility=Conference.Visibility.PUBLIC)

    is_global_privileged = user.is_superuser or (
        await user.global_role_assignments.filter(role__in=global_readable).aexists()
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


async def visible_tracks(
    user: User | AnonymousUser,
    conferences: Collection[Conference],
    global_readable: Collection[GlobalRole] = (GlobalRole.ADMIN, GlobalRole.READ_ALL),
) -> QuerySet[Track]:
    """Return the queryset of tracks within ``conferences`` visible to ``user``.

    The queryset includes:

    - all public tracks;
    - all tracks when the user is a superuser or holds any ``global_readable`` role;
    - private tracks whose parent conference the user administers; and
    - private tracks where the user has a track-admin role.
    """
    tracks = Track.objects.filter(conference__in=conferences, active=True)

    if not user.is_authenticated:
        return tracks.filter(visibility=Track.Visibility.PUBLIC)

    is_global_privileged = user.is_superuser or (
        await user.global_role_assignments.filter(role__in=global_readable).aexists()
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
    return tracks.filter(is_public | is_conference_admin | is_track_admin).distinct()


async def prefetch_tracks(
    *conferences: Conference,
    user: User | AnonymousUser,
    global_readable: Collection[GlobalRole] = (GlobalRole.ADMIN, GlobalRole.READ_ALL),
) -> Collection[Conference]:
    """Attach track lists to ``conferences`` according to ``visible_tracks`` rules."""
    tracks = await visible_tracks(user, conferences, global_readable)

    conference_tracks: dict[int, list[Track]] = defaultdict(list)
    async for track in tracks:
        conference_tracks[track.conference_id].append(track)

    for conference in conferences:
        conference.prefetched_tracks = conference_tracks[conference.id]

    return conferences


def validate_keyword_payload(
    *,
    keyword_texts: Collection[str],
    keyword_set_names: Collection[str],
) -> tuple[list[Keyword], list[KeywordSet]]:
    """Validate keyword lists and return the matching database objects.

    Raise HTTP 422 Unprocessable Entity error if any keywords or keyword sets do not
    exist.
    """
    provided_keywords = set(keyword_texts)
    keywords: list[Keyword] = []
    if provided_keywords:
        keywords = list(Keyword.objects.filter(text__in=provided_keywords))
        missing_keywords = provided_keywords - {keyword.text for keyword in keywords}
        if missing_keywords:
            message = _("Unknown keywords: {keywords}.").format(
                keywords=", ".join(sorted(missing_keywords)),
            )
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    provided_keyword_sets = set(keyword_set_names)
    keyword_sets: list[KeywordSet] = []
    if provided_keyword_sets:
        keyword_sets = list(
            KeywordSet.objects.filter(name__in=provided_keyword_sets).prefetch_related(
                "keywords"
            )
        )
        missing_keyword_sets = provided_keyword_sets - {
            keyword_set.name for keyword_set in keyword_sets
        }
        if missing_keyword_sets:
            message = _("Unknown keyword sets: {keyword_sets}.").format(
                keyword_sets=", ".join(sorted(missing_keyword_sets)),
            )
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    return keywords, keyword_sets

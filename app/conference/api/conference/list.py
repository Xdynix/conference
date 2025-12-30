from django.db.models import Prefetch, QuerySet
from ninja.pagination import paginate

from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.conference.types import ConferenceName
from app.core.types import HttpRequest
from app.ninja.pagination import cursor_pagination

from .core import ConferenceResponse, router

# TODO: Filtering and searching.


@router.get(
    "/conferences",
    response=list[ConferenceResponse],
    summary="List Conferences",
)
@paginate(cursor_pagination(cursor_field="name", cursor_type=ConferenceName))
async def list_conferences(request: HttpRequest) -> QuerySet[Conference]:
    """Return the conferences the current user may access plus the tracks they can see.

    Visibility rules:

    - Unauthenticated callers only see public conferences/tracks.
    - Superusers or users with `Admin`/`Read All` global roles see everything.
    - Authenticated users see a conference when it is public, when they hold any
      conference or track admin role (regardless of visibility), or when they hold any
      role and the conference is member-only.
    - Within a visible conference, tracks show up when they are public, when the user
      is an admin (at the conference or track level), or when the user holds any track
      role and the track is member-only.
    """
    user = await request.auser()

    visible_conferences = await ConferenceService.visible_conferences(user)
    visible_tracks = await ConferenceService.visible_tracks(user)
    return visible_conferences.prefetch_related(
        Prefetch(
            "tracks",
            queryset=visible_tracks,
            to_attr="visible_tracks",
        )
    )

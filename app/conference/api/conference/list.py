from django.db.models import Prefetch, QuerySet
from ninja.pagination import paginate

from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.core.types import HttpRequest
from app.ninja.pagination import CursorPagination

from .core import ConferenceResponse, router

# TODO: Filtering and searching.


@router.get(
    "/conferences",
    response=list[ConferenceResponse],
    summary="List Conferences",
)
@paginate(CursorPagination, cursor_field="name")
async def list_conferences(request: HttpRequest) -> QuerySet[Conference]:
    """Return the conferences the current user may access plus the tracks they can see.

    Visibility rules:

    - Unauthenticated callers only see public conferences/tracks.
    - Superusers or users with `Admin`/`Read All` global roles see everything.
    - Authenticated users see a conference when it is public, when they hold a
      conference admin role, or when they administer at least one of its tracks.
    - Within a visible conference, tracks show up when they are public or when the user
      is an admin either at the conference level or for the specific track.
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

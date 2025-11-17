from typing import Any

from django.db.models import QuerySet
from ninja.pagination import paginate

from app.conference.models import Conference
from app.conference.schemas import Conference as ConferenceSchema
from app.core.types import HttpRequest
from app.ninja.pagination import CursorPagination

from .core import prefetch_tracks, router, visible_conferences


class ConferencePaginator(CursorPagination[Conference, str]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(cursor_field="name", **kwargs)

    async def make_page(
        self,
        items: list[Any],
        pagination: CursorPagination.Input[str],
        request: HttpRequest,  # type: ignore[override]
    ) -> dict[str, Any]:
        page = await super().make_page(items, pagination, request)
        page[self.items_attribute] = await prefetch_tracks(
            *page[self.items_attribute],
            user=await request.auser(),
        )
        return page


# TODO: Filtering and searching.


@router.get(
    "/conferences",
    response=list[ConferenceSchema],
    summary="List Conferences",
)
@paginate(ConferencePaginator)
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
    conferences = await visible_conferences(user)
    return conferences

from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404

from app.conference.models import Conference
from app.conference.schemas import ConferenceDetail
from app.core.types import HttpRequest

from .core import prefetch_tracks, router, visible_conferences


@router.get(
    "/conferences/{slug:conference_name}",
    response=ConferenceDetail,
    summary="Get Conference",
)
async def get_conference(request: HttpRequest, conference_name: str) -> Conference:
    """Retrieve a single conference."""
    user = await request.auser()
    conferences: QuerySet[Conference] = await visible_conferences(user)
    conference = await aget_object_or_404(
        conferences.prefetch_related("keywords"),
        name=conference_name,
    )
    await prefetch_tracks(conference, user=user)
    return conference

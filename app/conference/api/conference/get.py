from django.shortcuts import aget_object_or_404

from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.conference.types import ConferenceDetail
from app.core.types import HttpRequest

from .core import prefetch_conference, router


@router.get(
    "/conferences/{slug:conference_name}",
    response=ConferenceDetail,
    summary="Get Conference",
)
async def get_conference(request: HttpRequest, conference_name: str) -> Conference:
    """Retrieve a single conference."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    return await prefetch_conference(conference, user)

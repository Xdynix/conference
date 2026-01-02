from django.shortcuts import aget_object_or_404
from ninja import Schema

from app.conference.models import Paper
from app.conference.services import ConferenceService
from app.conference.types import PaperCode, PaperTitle
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest

from .core import router


class RegistrablePaperResponse(Schema):
    code: PaperCode
    title: PaperTitle


@router.get(
    "/conferences/{slug:conference_name}/registrable-papers",
    response=list[RegistrablePaperResponse],
    summary="List Registrable Papers",
    auth=is_authenticated,
)
async def list_registrable_papers(
    request: AuthedHttpRequest,
    conference_name: str,
) -> list[Paper]:
    """Lists papers available for selection during registration.

    Returns announced, accepted papers when registration is enabled. Returns an empty
    list when registration is disabled.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    if not conference.registration_enabled:
        return []

    papers = conference.papers.registrable()
    return [paper async for paper in papers]

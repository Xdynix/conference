from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Paper
from app.conference.services import PaperService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaperDetailResponse, prefetch_paper, router


class RelocatePaperRequest(Schema):
    target_track: ULID


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:relocate",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Relocate Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def relocate_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: RelocatePaperRequest,
) -> Paper:
    """Relocate a paper to a different track within the same conference."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    target_track = (
        await conference.tracks.active().filter(uid=payload.target_track).afirst()
    )
    if target_track is None:
        raise make_validation_error(
            path="target_track",
            message=_("Track not found."),
        )

    try:
        paper = await sync_to_async(PaperService.relocate_paper)(paper, target_track)
    except ValueError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Paper relocated.",
        paper_code=paper.code,
        conference_name=conference.name,
        target_track_uid=str(target_track.uid),
        actor_uid=str(user.uid),
    )

    return await prefetch_paper(conference, paper, user, request)

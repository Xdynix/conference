from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, TrackRole
from app.conference.services import (
    ConferenceAccessService,
    ConferenceService,
    PaperService,
)
from app.conference.services.paper import PaperStateError
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import router


@router.delete(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}",
    response={
        HTTPStatus.NO_CONTENT: None,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Delete My Paper",
    auth=is_authenticated,
)
async def delete_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> tuple[int, None]:
    """Remove a paper from the conference.

    Papers can only be deleted while in Draft or Submitted state. Once deleted, the
    paper is removed from all paper listings and conference statistics.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active().filter(owner=user),
        code=paper_code,
    )

    try:
        await sync_to_async(PaperService.delete_paper)(paper=paper, mode="author")
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Paper deleted by owner.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return HTTPStatus.NO_CONTENT, None


@router.delete(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}",
    response={
        HTTPStatus.NO_CONTENT: None,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Delete Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def delete_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> tuple[int, None]:
    """Remove a paper from the conference as an admin.

    Track admins can delete papers in Draft, Submitted, or Under Review state.
    Conference admins can delete papers in any state. Withdrawn papers cannot be
    deleted.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        await PaperService.visible_papers(conference, user),
        code=paper_code,
    )

    ctx = await ConferenceAccessService.context(
        conference=conference,
        user=user,
        global_roles=(GlobalRole.ADMIN,),
    )
    mode: Literal["admin", "track_admin"] = (
        "admin" if ctx.has_full_conference_scope else "track_admin"
    )

    try:
        await sync_to_async(PaperService.delete_paper)(paper=paper, mode=mode)
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Paper deleted by admin.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return HTTPStatus.NO_CONTENT, None

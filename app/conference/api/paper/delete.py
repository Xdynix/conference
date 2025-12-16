from http import HTTPStatus

from django.shortcuts import aget_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from loguru import logger
from ninja.errors import HttpError

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import (
    ConferenceAccessService,
    ConferenceService,
    PaperService,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import router


async def remove_paper(paper: Paper) -> None:
    """Soft delete a paper by setting ``delete_time``.

    Raises:
        ValueError: If the paper is withdrawn.
    """
    if paper.withdraw_time is not None:
        raise ValueError(_("Withdrawn papers cannot be deleted."))

    paper.delete_time = timezone.now()
    await paper.asave(update_fields=["delete_time", "update_time"])


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

    papers = conference.papers.active().filter(owner=user)
    paper = await aget_object_or_404(papers, code=paper_code)

    if paper.state not in (Paper.State.DRAFT, Paper.State.SUBMITTED):
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Paper must be in Draft or Submitted state to delete."),
        )

    try:
        await remove_paper(paper)
    except ValueError as exc:
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

    papers = await PaperService.visible_papers(conference, user)
    paper = await aget_object_or_404(papers, code=paper_code)

    ctx = await ConferenceAccessService.context(
        conference=conference,
        user=user,
        global_roles=(GlobalRole.ADMIN,),
    )
    if not ctx.has_full_conference_scope and paper.state in Paper.State.decided():
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _(
                "Track admins can only delete papers in Draft, Submitted, "
                "or Under Review state."
            ),
        )

    try:
        await remove_paper(paper)
    except ValueError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Paper deleted by admin.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return HTTPStatus.NO_CONTENT, None

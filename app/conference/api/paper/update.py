from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, PatchDict, Schema
from ninja.errors import HttpError

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.conference.services import (
    ConferenceAccessService,
    ConferenceService,
    KeywordService,
    PaperService,
)
from app.conference.services.paper import AuthorData
from app.conference.types import (
    KeywordText,
    PaperAbstract,
    PaperAuthor,
    PaperContribution,
    PaperTitle,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router


class PaperSchema(Schema):
    title: PaperTitle
    abstract: PaperAbstract
    contribution: PaperContribution
    keywords: list[KeywordText] = Field(max_length=50)
    authors: list[PaperAuthor] = Field(max_length=100)


async def apply_paper_update(
    user: User,
    paper: Paper,
    payload: PatchDict[UpdatePaperSchema],
    *,
    flow: Literal["author", "admin"],
) -> Paper:
    """Shared implementation for paper update endpoints.

    Args:
        user: Authenticated user updating the paper.
        paper: The paper to update.
        payload: Update data with optional fields.
        flow: The update flow. "author" enforces Draft state restriction. "admin" allows
            updates in any state.
    """
    if paper.withdraw_time is not None:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Withdrawn papers cannot be updated."),
        )

    if flow == "author":
        if paper.state != Paper.State.DRAFT:
            raise HttpError(
                HTTPStatus.BAD_REQUEST,
                _("Paper must be in Draft state to update."),
            )
    else:
        if paper.state in Paper.State.decided():
            ctx = await ConferenceAccessService.context(
                conference=paper.conference,
                user=user,
                global_roles=(GlobalRole.ADMIN,),
            )
            if not ctx.has_full_conference_scope:
                raise HttpError(
                    HTTPStatus.BAD_REQUEST,
                    _("Only conference admins can update papers after decision."),
                )

    try:
        keywords = await KeywordService.validate_keyword_texts(
            payload.get("keywords")  # type: ignore[func-returns-value]
        )
    except ValueError as exc:
        raise make_validation_error(path="keywords", message=str(exc)) from exc

    authors: list[AuthorData] | None = payload.get("authors")

    return await sync_to_async(PaperService.update_paper)(
        paper=paper,
        title=payload.get("title"),
        abstract=payload.get("abstract"),
        contribution=payload.get("contribution"),
        keywords=keywords,
        authors=authors,
    )


@router.patch(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}",
    response={
        HTTPStatus.OK: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update My Paper",
    auth=is_authenticated,
)
async def update_my_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: PatchDict[PaperSchema],
) -> Paper:
    """Update paper metadata, authors, and keywords.

    Only papers in Draft state can be updated. All fields are optional. When provided,
    authors and keywords completely replace existing values.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    papers = conference.papers.active().filter(owner=user)
    paper = await aget_object_or_404(papers, code=paper_code)

    updated = await apply_paper_update(user, paper, payload, flow="author")

    logger.info(
        "Paper updated by owner.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_paper(updated)


@router.patch(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def update_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: PatchDict[PaperSchema],
) -> Paper:
    """Update paper metadata, authors, and keywords as an admin.

    Track admins can update papers in Draft, Submitted, or Under Review state.
    Conference admins can update papers in any state, including decided papers.
    All fields are optional. When provided, authors and keywords completely replace
    existing values.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    papers = await PaperService.visible_papers(conference, user)
    paper = await aget_object_or_404(
        papers.select_related("conference"),
        code=paper_code,
    )

    updated = await apply_paper_update(user, paper, payload, flow="admin")

    logger.info(
        "Paper updated by admin.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_paper(updated)

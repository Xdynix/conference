from http import HTTPStatus
from typing import Any, Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
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
from app.conference.services.paper import (
    AuthorData,
    PaperStateError,
)
from app.conference.types import (
    KeywordText,
    PaperAbstract,
    PaperAuthor,
    PaperContribution,
    PaperTitle,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
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
    paper: Paper,
    payload: dict[str, Any],
    *,
    mode: Literal["author", "track_admin", "admin"] = "author",
) -> Paper:
    """Update paper metadata, authors, and keywords.

    Validates keywords and calls the paper service to apply updates.
    """
    try:
        keywords = await KeywordService.validate_keyword_texts(
            payload.get("keywords")  # type: ignore[func-returns-value]
        )
    except ValueError as exc:
        raise make_validation_error(path="keywords", message=str(exc)) from exc

    authors: list[AuthorData] | None = payload.get("authors")

    try:
        return await sync_to_async(PaperService.update_paper)(
            paper=paper,
            mode=mode,
            title=payload.get("title"),
            abstract=payload.get("abstract"),
            contribution=payload.get("contribution"),
            keywords=keywords,
            authors=authors,
        )
    except PaperStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc


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

    paper = await aget_object_or_404(
        conference.papers.active().filter(owner=user),
        code=paper_code,
    )

    updated = await apply_paper_update(paper, payload)

    logger.info(
        "Paper updated by owner.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_paper(conference, updated, user)


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

    updated = await apply_paper_update(paper, payload, mode=mode)

    logger.info(
        "Paper updated by admin.",
        paper_code=paper.code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_paper(conference, updated, user)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Schema
from ulid import ULID

from app.conference.models import Paper, Track
from app.conference.services import ConferenceService, KeywordService, PaperService
from app.conference.services.paper import AuthorData, NoCodePoolError
from app.conference.types import (
    KeywordText,
    PaperAbstract,
    PaperAuthor,
    PaperContribution,
    PaperTitle,
)
from app.core.auth import is_authenticated
from app.core.models import User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import UserPaperDetailResponse, prefetch_paper, router


class CreatePaperRequest(Schema):
    track: ULID
    title: PaperTitle
    abstract: PaperAbstract = ""
    contribution: PaperContribution = ""
    keywords: list[KeywordText] = Field(default_factory=list, max_length=50)
    authors: list[PaperAuthor] = Field(default_factory=list, max_length=100)


async def persist_paper_entry(
    user: User,
    conference_name: str,
    payload: CreatePaperRequest,
    *,
    strict: bool,
) -> Paper:
    """Shared implementation for paper creation endpoints.

    Args:
        user: Authenticated user creating the paper.
        conference_name: Slug of the conference receiving the paper.
        payload: Paper details to persist.
        strict: If ``True``, enforces that the track accepts submissions (author flow).
            If ``False``, bypasses this check (admin flow).
    """
    conferences = await ConferenceService.visible_conferences(user)
    conference = await aget_object_or_404(conferences, name=conference_name)

    tracks = await ConferenceService.visible_tracks(user)
    try:
        track = await tracks.aget(conference=conference, uid=payload.track)
    except Track.DoesNotExist as exc:
        raise make_validation_error(
            path="track",
            message=_("Invalid track UID."),
        ) from exc

    if strict and not track.accepts_submissions:
        raise make_validation_error(
            path="track",
            message=_("This track is not currently accepting submissions."),
        )

    try:
        keywords = await KeywordService.validate_keyword_texts(payload.keywords)
    except ValueError as exc:
        raise make_validation_error(path="keywords", message=str(exc)) from exc

    authors: list[AuthorData] = [
        AuthorData(
            given_name=author.given_name,
            family_name=author.family_name,
            affiliation=author.affiliation,
            region_code=author.region_code,
            email=author.email,
            phone=author.phone,
            corresponding=author.corresponding,
        )
        for author in payload.authors
    ]

    try:
        return await sync_to_async(PaperService.create_paper)(
            track=track,
            owner=user,
            title=payload.title,
            abstract=payload.abstract,
            contribution=payload.contribution,
            keywords=keywords,
            authors=authors,
        )
    except NoCodePoolError as exc:
        raise make_validation_error(
            path="track",
            message=_("This track is not configured for paper submissions."),
        ) from exc


@router.post(
    "/conferences/{slug:conference_name}/my-papers",
    response={
        HTTPStatus.CREATED: UserPaperDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Draft",
    auth=is_authenticated,
)
async def create_draft(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreatePaperRequest,
) -> tuple[int, Paper]:
    """Start a new paper submission by creating a draft in the specified track.

    Upload a submission file and use the submit endpoint to mark the paper ready for
    review.
    """
    user = await request.auser()
    paper = await persist_paper_entry(user, conference_name, payload, strict=True)

    logger.info(
        "Draft created.",
        paper_code=paper.code,
        conference_name=conference_name,
        track_uid=str(paper.track.uid),
        user_uid=str(user.uid),
    )

    return HTTPStatus.CREATED, await prefetch_paper(paper)

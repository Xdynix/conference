from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Schema, Status
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Paper, Track, TrackRole
from app.conference.services import (
    ClaimService,
    ConferenceAccessService,
    ConferenceService,
    KeywordService,
    PaperService,
)
from app.conference.services.paper import AuthorData, NoCodePoolError
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


class CreatePaperRequest(Schema):
    track: ULID
    title: PaperTitle
    abstract: PaperAbstract = ""
    contribution: PaperContribution = ""
    keywords: list[KeywordText] = Field(default_factory=list, max_length=50)
    authors: list[PaperAuthor] = Field(default_factory=list, max_length=100)


class AdminCreatePaperRequest(CreatePaperRequest):
    auto_claim: bool = False


async def persist_paper_entry(
    user: User,
    conference: Conference,
    payload: CreatePaperRequest,
    *,
    flow: Literal["author", "admin"],
) -> Paper:
    """Shared implementation for paper creation endpoints.

    Args:
        user: Authenticated user creating the paper.
        conference: The conference receiving the paper.
        payload: Paper details to persist.
        flow: The creation flow. "author" enforces that the track has submissions
            enabled. "admin" allows submission to open tracks or to closed tracks where
            the user has admin permission.
    """
    tracks = await ConferenceService.visible_tracks(user)
    try:
        track = await tracks.aget(conference=conference, uid=payload.track)
    except Track.DoesNotExist as exc:
        raise make_validation_error(
            path="track",
            message=_("Invalid track UID."),
        ) from exc

    if flow == "author":
        if not track.submissions_enabled:
            raise make_validation_error(
                path="track",
                message=_("This track is not currently accepting submissions."),
            )
    else:
        # Allow if submissions are enabled or the user has admin permission on the
        # track.
        if not track.submissions_enabled:
            has_permission = await ConferenceAccessService.can_admin_track(
                conference=conference,
                track=track,
                user=user,
                global_roles=(GlobalRole.ADMIN,),
            )
            if not has_permission:
                raise make_validation_error(
                    path="track",
                    message=_(
                        "You do not have permission to create papers in this track."
                    ),
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

    auto_claim = isinstance(payload, AdminCreatePaperRequest) and payload.auto_claim

    def _create() -> Paper:
        with transaction.atomic():
            try:
                paper = PaperService.create_paper(
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

            if auto_claim:
                try:
                    ClaimService.set_claim(paper=paper)
                except ValueError as exc:
                    raise make_validation_error(
                        path="auto_claim",
                        message=str(exc),
                    ) from exc

            return paper

    return await sync_to_async(_create)()


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
) -> Status[Paper]:
    """Start a new paper submission by creating a draft in the specified track.

    Upload a submission file and use the submit endpoint to mark the paper ready for
    review.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    paper = await persist_paper_entry(user, conference, payload, flow="author")

    await audit(
        request=request,
        action=AuditAction.PAPER_CREATE,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )


@router.post(
    "/conferences/{slug:conference_name}/papers",
    response={
        HTTPStatus.CREATED: PaperDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def create_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: AdminCreatePaperRequest,
) -> Status[Paper]:
    """Create a paper as an admin.

    This bypasses the track's submissions-enabled check, allowing creation of invited
    papers or papers for tracks that are not currently open for submissions. When
    ``auto_claim`` is true, a claim is created for deferred ownership transfer to the
    corresponding author.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await persist_paper_entry(user, conference, payload, flow="admin")

    await audit(
        request=request,
        action=AuditAction.PAPER_CREATE,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )

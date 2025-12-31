from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.conf import settings
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import File
from ninja.errors import HttpError
from ninja.files import UploadedFile

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Paper,
    PaperState,
    TrackRole,
)
from app.conference.services import (
    ConferenceAccessService,
    ConferenceService,
    PaperService,
    RevisionService,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse
from app.utils.files import UploadValidationError

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router

# TODO: Implement virus and malicious file scanning on the uploaded files.


@router.post(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}/submissions",
    response={
        HTTPStatus.CREATED: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create My Submission",
    auth=is_authenticated,
)
async def create_my_submission(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    file: File[UploadedFile],
) -> tuple[int, Paper]:
    """Upload a submission file for a paper.

    Creates a new revision of the submission. Only papers in Draft or Submitted state
    can have submissions uploaded.
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

    if paper.withdraw_time is not None:
        raise HttpError(HTTPStatus.BAD_REQUEST, _("Withdrawn papers cannot be edited."))

    if paper.state not in (PaperState.DRAFT, PaperState.SUBMITTED):
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _(
                "Submissions can only be uploaded for papers in "
                "Draft or Submitted state."
            ),
        )

    try:
        submission = await sync_to_async(RevisionService.create_submission)(
            paper=paper,
            file=file,
            uploader=user,
            max_size=settings.MAX_SUBMISSION_SIZE,
            allowed_types=settings.ALLOWED_SUBMISSION_TYPES,
        )
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    logger.info(
        "Submission uploaded.",
        paper_code=paper.code,
        conference_name=conference.name,
        revision=submission.revision,
        user_uid=str(user.uid),
    )

    return HTTPStatus.CREATED, await prefetch_paper(conference, paper, user, request)


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/submissions",
    response={
        HTTPStatus.CREATED: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Submission",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def create_submission(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    file: File[UploadedFile],
) -> tuple[int, Paper]:
    """Upload a submission file for a paper as an admin.

    Track admins can upload to papers in Draft, Submitted, or Under Review state.
    Conference admins can upload to papers in any state except Withdrawn. Admin
    uploads allow 4x the standard submission size limit.
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

    if paper.withdraw_time is not None:
        raise HttpError(HTTPStatus.BAD_REQUEST, _("Withdrawn papers cannot be edited."))

    if paper.state in PaperState.decided():
        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=user,
            global_roles=(GlobalRole.ADMIN,),
        )
        if not ctx.has_full_conference_scope:
            raise HttpError(
                HTTPStatus.BAD_REQUEST,
                _(
                    "Only conference admins can upload paper submissions "
                    "after decision."
                ),
            )

    try:
        submission = await sync_to_async(RevisionService.create_submission)(
            paper=paper,
            file=file,
            uploader=user,
            skip_cleanup=True,
            max_size=settings.MAX_SUBMISSION_SIZE * 4,
            allowed_types=settings.ALLOWED_SUBMISSION_TYPES,
        )
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    logger.info(
        "Submission uploaded by admin.",
        paper_code=paper.code,
        conference_name=conference.name,
        revision=submission.revision,
        user_uid=str(user.uid),
    )

    return HTTPStatus.CREATED, await prefetch_paper(conference, paper, user, request)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.conf import settings
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import File
from ninja.errors import HttpError
from ninja.files import UploadedFile

from app.conference.models import Paper
from app.conference.services import ConferenceService
from app.conference.services.revision import RevisionService
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse
from app.utils.upload import UploadValidationError

from .core import UserPaperDetailResponse, prefetch_paper, router


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

    if paper.state not in (Paper.State.DRAFT, Paper.State.SUBMITTED):
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

    return HTTPStatus.CREATED, await prefetch_paper(paper)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.conf import settings
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import File, Status
from ninja.errors import HttpError
from ninja.files import UploadedFile

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import (
    has_any_conference_or_track_roles,
    has_any_conference_roles,
)
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
from app.conference.services.revision import FinalRevisionLimitError
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse
from app.utils.files import UploadValidationError

from .core import PaperDetailResponse, UserPaperDetailResponse, prefetch_paper, router

# TODO: Implement virus and malicious file scanning on the uploaded files.


def file_meta(file: UploadedFile) -> dict[str, str | int]:
    """Extract auditable metadata from an uploaded file."""
    return {"name": file.name or "", "size": file.size or 0}


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
) -> Status[Paper]:
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

    await audit(
        request=request,
        action=AuditAction.PAPER_UPLOAD_SUBMISSION,
        resource=paper,
        scope=conference.name,
        payload={"file": file_meta(file)},
        detail={"revision": submission.revision},
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )


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
) -> Status[Paper]:
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

    await audit(
        request=request,
        action=AuditAction.PAPER_UPLOAD_SUBMISSION,
        resource=paper,
        scope=conference.name,
        payload={"file": file_meta(file)},
        detail={"revision": submission.revision},
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )


@router.post(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}/finals",
    response={
        HTTPStatus.CREATED: UserPaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create My Final",
    auth=is_authenticated,
)
async def create_my_final(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    source_file: File[UploadedFile],
    # NOTE: Django Ninja doesn't handle `File[T] | None` for optional file uploads;
    # using `| None` causes the parameter to always resolve as None. Use `= None`
    # default without union type annotation as a workaround.
    viewable_file: File[UploadedFile] = None,  # type: ignore[assignment]
) -> Status[Paper]:
    """Upload final version files for a paper.

    Creates a new revision of the final. Only papers in Accepted or Accepted (Revision
    Needed) state can have finals uploaded. The revision limit is enforced.
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

    if paper.visible_state not in (
        PaperState.ACCEPTED,
        PaperState.ACCEPTED_REVISION_NEEDED,
    ):
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Finals can only be uploaded for accepted papers."),
        )

    try:
        final = await sync_to_async(RevisionService.create_final)(
            paper=paper,
            source_file=source_file,
            viewable_file=viewable_file,
            uploader=user,
            enforce_limit=True,
            source_max_size=settings.MAX_FINAL_SOURCE_SIZE,
            source_allowed_types=settings.ALLOWED_FINAL_SOURCE_TYPES,
            viewable_max_size=settings.MAX_FINAL_VIEWABLE_SIZE,
            viewable_allowed_types=settings.ALLOWED_FINAL_VIEWABLE_TYPES,
        )
    except FinalRevisionLimitError as exc:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Final revision limit exceeded."),
        ) from exc
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_UPLOAD_FINAL,
        resource=paper,
        scope=conference.name,
        payload={
            "source_file": file_meta(source_file),
            "viewable_file": file_meta(viewable_file) if viewable_file else None,
        },
        detail={"revision": final.revision},
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/finals",
    response={
        HTTPStatus.CREATED: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Final",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def create_final(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    source_file: File[UploadedFile],
    # NOTE: Django Ninja doesn't handle `File[T] | None` for optional file uploads;
    # using `| None` causes the parameter to always resolve as None. Use `= None`
    # default without union type annotation as a workaround.
    viewable_file: File[UploadedFile] = None,  # type: ignore[assignment]
) -> Status[Paper]:
    """Upload final version files for a paper as an admin.

    Admin uploads bypass the revision limit. Allows 4x the standard size limits.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    if paper.withdraw_time is not None:
        raise HttpError(HTTPStatus.BAD_REQUEST, _("Withdrawn papers cannot be edited."))

    try:
        final = await sync_to_async(RevisionService.create_final)(
            paper=paper,
            source_file=source_file,
            viewable_file=viewable_file,
            uploader=user,
            enforce_limit=False,
            source_max_size=settings.MAX_FINAL_SOURCE_SIZE * 4,
            source_allowed_types=settings.ALLOWED_FINAL_SOURCE_TYPES,
            viewable_max_size=settings.MAX_FINAL_VIEWABLE_SIZE * 4,
            viewable_allowed_types=settings.ALLOWED_FINAL_VIEWABLE_TYPES,
        )
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_UPLOAD_FINAL,
        resource=paper,
        scope=conference.name,
        payload={
            "source_file": file_meta(source_file),
            "viewable_file": file_meta(viewable_file) if viewable_file else None,
        },
        detail={"revision": final.revision},
    )

    return Status(
        HTTPStatus.CREATED,
        await prefetch_paper(conference, paper, user, request),
    )

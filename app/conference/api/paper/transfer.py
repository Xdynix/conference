from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Schema

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Paper
from app.conference.services import PaperService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaperDetailResponse, prefetch_paper, router


class TransferPaperRequest(Schema):
    new_owner_email: EmailStr


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}:transfer",
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Transfer Paper",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def transfer_paper(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: TransferPaperRequest,
) -> Paper:
    """Transfer paper ownership to another user."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper: Paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    new_owner = (
        await User.objects.active()
        .filter(email__iexact=payload.new_owner_email)
        .afirst()
    )
    if new_owner is None:
        raise make_validation_error(
            path="new_owner_email",
            message=_("User not found."),
        )

    paper = await sync_to_async(PaperService.transfer_paper)(
        paper=paper,
        new_owner=new_owner,
    )

    await audit(
        request=request,
        action=AuditAction.PAPER_TRANSFER,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_paper(conference, paper, user, request)

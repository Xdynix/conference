from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, TrackRole
from app.conference.services import InvitationService
from app.conference.services.conference import InsufficientRolePermission
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import router


@router.delete(
    "/conferences/{slug:conference_name}/invitations/{ulid:invitation_id}",
    response={
        HTTPStatus.NO_CONTENT: None,
        HTTPStatus.FORBIDDEN: ErrorResponse,
    },
    summary="Delete Invitation",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def delete_invitation(
    request: AuthedHttpRequest,
    conference_name: str,
    invitation_id: ULID,
) -> tuple[int, None]:
    """Delete a conference invitation."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    invitations = await InvitationService.visible_invitations(conference, user)
    is_visible = await invitations.filter(uid=invitation_id).aexists()
    if not is_visible:
        raise Http404

    try:
        await sync_to_async(InvitationService.delete_invitation)(
            invitation_uid=invitation_id,
            user=user,
        )
    except InsufficientRolePermission as exc:
        raise HttpError(HTTPStatus.FORBIDDEN, str(exc)) from exc

    logger.info("Invitation deleted.", conference=conference, user=user)

    return HTTPStatus.NO_CONTENT, None

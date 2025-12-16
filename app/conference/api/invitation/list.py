from typing import assert_never

from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja.pagination import paginate

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Invitation, TrackRole
from app.conference.services import InvitationService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import CursorPagination

from .core import InvitationResponse, router, with_invitation_prefetch


@router.get(
    "/conferences/{slug:conference_name}/invitations",
    response=list[InvitationResponse],
    summary="List Invitations",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
@paginate(CursorPagination, cursor_field="uid")
async def list_invitations(
    request: AuthedHttpRequest,
    conference_name: str,
    state: Invitation.State | None = None,
) -> QuerySet[Invitation]:
    """Return invitations for the conference visible to the current user.

    Visibility rules:

    - Superusers and users with `Admin`/`Read All` global roles see all invitations.
    - Conference admins (chairs and secretaries) see all invitations.
    - Track admins see invitations that contain ONLY track roles for their tracks (no
      conference roles).
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    invitations = await InvitationService.visible_invitations(conference, user)

    if state is not None:
        match state:
            case Invitation.State.PENDING:
                invitations = invitations.filter(accept_time=None, reject_time=None)
            case Invitation.State.ACCEPTED:
                invitations = invitations.filter(accept_time__isnull=False)
            case Invitation.State.REJECTED:
                invitations = invitations.filter(
                    accept_time=None,
                    reject_time__isnull=False,
                )
            case _ as unreachable:
                assert_never(unreachable)

    return with_invitation_prefetch(invitations)

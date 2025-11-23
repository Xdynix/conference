from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Invitation, TrackRole
from app.conference.services import InvitationService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import InvitationResponse, router


@router.get(
    "/conferences/{slug:conference_name}/invitations/{ulid:invitation_id}",
    response=InvitationResponse,
    summary="Get Invitation",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def get_invitation(
    request: AuthedHttpRequest,
    conference_name: str,
    invitation_id: ULID,
) -> Invitation:
    """Retrieve a single invitation."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    invitations = await InvitationService.visible_invitations(conference, user)

    return await aget_object_or_404(
        invitations.prefetch_related(
            "interested_keywords",
            "conference_role_entries",
            "track_role_entries__track",
        ),
        uid=invitation_id,
    )

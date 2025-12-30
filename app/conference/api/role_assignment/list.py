from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja.pagination import paginate
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    TrackRole,
)
from app.conference.services import RoleAssignmentService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import cursor_pagination

from .core import RoleAssignmentResponse, router, with_role_assignment_prefetch


@router.get(
    "/conferences/{slug:conference_name}/role-assignments",
    response=list[RoleAssignmentResponse],
    summary="List Role Assignments",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
@paginate(cursor_pagination(cursor_field="uid", cursor_type=ULID))
async def list_role_assignments(
    request: AuthedHttpRequest,
    conference_name: str,
) -> QuerySet[User]:
    """Return users with role assignments visible to the current user.

    Visibility rules:

    - Superusers and users with `Admin`/`Read All` global roles see all users with
      assignments and all their roles.
    - Conference admins (chairs and secretaries) see all users with assignments and all
      their roles.
    - Track admins see only users with roles on tracks they administer. Conference roles
      are excluded from the response, and track roles are limited to their administered
      tracks.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    users = await RoleAssignmentService.visible_users_with_roles(conference, user)
    return await with_role_assignment_prefetch(
        users,
        conference=conference,
        requesting_user=user,
    )

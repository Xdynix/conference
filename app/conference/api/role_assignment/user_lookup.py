from http import HTTPStatus

from django.shortcuts import aget_object_or_404

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import ConferenceRole, TrackRole
from app.conference.types import Profile as ProfileSchema
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest, EmailStr
from app.core.types import User as UserSchema
from app.ninja.errors import ErrorResponse

from .core import router


class LookupRoleAssignmentUserResponse(UserSchema):
    profile: ProfileSchema | None = None


@router.get(
    # Conference slug scopes auth and signals this route is for conference role
    # workflow, not the general `GET /users` surface; lookup itself scans active users
    # globally.
    "/conferences/{slug:conference_name}/users",
    response={
        HTTPStatus.OK: LookupRoleAssignmentUserResponse,
        HTTPStatus.NOT_FOUND: ErrorResponse,
    },
    summary="Lookup Role Assignment User",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def lookup_role_assignment_user(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,  # noqa: ARG001
    email: EmailStr,
) -> User:
    """Lookup a user by email for the role-assignment workflow."""
    return await aget_object_or_404(
        User.objects.active().select_related("profile"),
        email__iexact=email,
    )

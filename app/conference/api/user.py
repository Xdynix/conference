from http import HTTPStatus

from django.shortcuts import aget_object_or_404
from ninja import Router

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import ConferenceRole, TrackRole
from app.conference.types import ConferenceUser
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse

router = Router(tags=["Conference User"], exclude_none=True)


@router.get(
    # Conference slug scopes auth and signals this route is for conference role
    # workflow, not the general `GET /users` surface; lookup itself scans active users
    # globally.
    "/conferences/{slug:conference_name}/users",
    response={
        HTTPStatus.OK: ConferenceUser,
        HTTPStatus.NOT_FOUND: ErrorResponse,
    },
    summary="Lookup Conference User",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def lookup_conference_user(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,  # noqa: ARG001
    email: EmailStr,
) -> User:
    """Lookup a user by email."""
    return await aget_object_or_404(
        User.objects.active().select_related("profile"),
        email__iexact=email,
    )

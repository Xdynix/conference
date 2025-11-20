from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, UserConferenceProfile
from app.conference.services import ConferenceService
from app.conference.types import UserConferenceProfile as UserConferenceProfileSchema
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest

from .core import router


@router.get(
    "/conferences/{slug:conference_name}/users/me/profile",
    response=UserConferenceProfileSchema,
    summary="Get My Conference Profile",
    auth=is_authenticated,
)
async def get_current_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
) -> UserConferenceProfile:
    """Return the current user's profile for the given conference."""
    user = await request.auser()
    conferences = await ConferenceService.visible_conferences(user)
    conference = await aget_object_or_404(conferences, name=conference_name)

    profile, _ = await UserConferenceProfile.objects.aget_or_create(
        user=user,
        conference=conference,
    )
    return await UserConferenceProfile.objects.prefetch_related(
        "interested_keywords"
    ).aget(pk=profile.pk)


@router.get(
    "/conferences/{slug:conference_name}/users/{ulid:user_id}/profile",
    response=UserConferenceProfileSchema,
    summary="Get User Conference Profile",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def get_user_conference_profile(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    user_id: ULID,
) -> UserConferenceProfile:
    """Return a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.filter(active=True),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )

    profile, _ = await UserConferenceProfile.objects.aget_or_create(
        user=user,
        conference=conference,
    )
    return await UserConferenceProfile.objects.prefetch_related(
        "interested_keywords"
    ).aget(pk=profile.pk)

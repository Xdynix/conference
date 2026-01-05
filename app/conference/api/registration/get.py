from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Registration
from app.conference.services import ConferenceService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import (
    RegistrationResponse,
    UserRegistrationResponse,
    prefetch_registration,
    router,
)


@router.get(
    "/conferences/{slug:conference_name}/my-registrations/{ulid:registration_uid}",
    response=UserRegistrationResponse,
    summary="Get My Registration",
    auth=is_authenticated,
)
async def get_my_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
) -> Registration:
    """Returns a specific registration created by the current user."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    registrations = conference.registrations.filter(user=user)

    registration = await aget_object_or_404(registrations, uid=registration_uid)
    return await prefetch_registration(registration, request)


@router.get(
    "/conferences/{slug:conference_name}/registrations/{ulid:registration_uid}",
    response=RegistrationResponse,
    summary="Get Registration",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def get_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
) -> Registration:
    """Returns a specific registration. Includes user information for admin review."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    registration = await aget_object_or_404(
        conference.registrations.all(),
        uid=registration_uid,
    )
    return await prefetch_registration(registration, request)

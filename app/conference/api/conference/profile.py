from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import Field, PatchDict, Schema
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, UserConferenceProfile
from app.conference.services import ConferenceService, UserConferenceProfileService
from app.conference.types import DesiredPaperCount, KeywordText
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import make_validation_error

from .core import router


class UserConferenceProfileResponse(Schema):
    desired_paper_count: DesiredPaperCount
    interested_keywords: list[KeywordText]

    @staticmethod
    def resolve_interested_keywords(profile: UserConferenceProfile) -> list[str]:
        return [keyword.text for keyword in profile.interested_keywords.all()]


async def get_visible_conference(user: User, conference_name: str) -> Conference:
    """Get a conference visible to the user."""
    conferences = await ConferenceService.visible_conferences(user)
    return await aget_object_or_404(conferences, name=conference_name)


@router.get(
    "/conferences/{slug:conference_name}/users/me/profile",
    response=UserConferenceProfileResponse,
    summary="Get My Conference Profile",
    auth=is_authenticated,
)
async def get_current_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
) -> UserConferenceProfile:
    """Return the current user's profile for the given conference."""
    user = await request.auser()
    conference = await get_visible_conference(user, conference_name)

    profile = await UserConferenceProfileService.get_or_create_profile(
        user=user,
        conference=conference,
    )
    return await UserConferenceProfileService.load_profile_with_keywords(profile)


@router.get(
    "/conferences/{slug:conference_name}/users/{ulid:user_id}/profile",
    response=UserConferenceProfileResponse,
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
        Conference.objects.active(),
        name=conference_name,
    )
    user = await aget_object_or_404(User.objects.active(), uid=user_id)

    profile = await UserConferenceProfileService.get_or_create_profile(
        user=user,
        conference=conference,
    )
    return await UserConferenceProfileService.load_profile_with_keywords(profile)


class UserConferenceProfileSchema(Schema):
    desired_paper_count: DesiredPaperCount
    interested_keywords: list[KeywordText] = Field(max_length=100)


@router.patch(
    "/conferences/{slug:conference_name}/users/me/profile",
    response=UserConferenceProfileResponse,
    summary="Update My Conference Profile",
    auth=is_authenticated,
)
async def update_current_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: PatchDict[UserConferenceProfileSchema],
) -> UserConferenceProfile:
    """Update the current user's profile for the given conference."""
    user = await request.auser()
    conference = await get_visible_conference(user, conference_name)

    profile = await UserConferenceProfileService.get_or_create_profile(
        user=user,
        conference=conference,
    )

    if payload:
        try:
            await UserConferenceProfileService.update_profile(
                profile=profile,
                desired_paper_count=payload.get("desired_paper_count"),
                interested_keywords=payload.get("interested_keywords"),
            )
        except ValueError as exc:
            raise make_validation_error(
                path="interested_keywords",
                message=str(exc),
            ) from exc

    logger.info(
        "User updated conference profile.",
        user=user,
        conference=conference,
    )

    return await UserConferenceProfileService.load_profile_with_keywords(profile)


@router.patch(
    "/conferences/{slug:conference_name}/users/{ulid:user_id}/profile",
    response=UserConferenceProfileResponse,
    summary="Update User Conference Profile",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def update_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
    user_id: ULID,
    payload: PatchDict[UserConferenceProfileSchema],
) -> UserConferenceProfile:
    """Update a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.active(),
        uid=user_id,
    )

    profile = await UserConferenceProfileService.get_or_create_profile(
        user=user,
        conference=conference,
    )

    if payload:
        try:
            await UserConferenceProfileService.update_profile(
                profile=profile,
                desired_paper_count=payload.get("desired_paper_count"),
                interested_keywords=payload.get("interested_keywords"),
            )
        except ValueError as exc:
            raise make_validation_error(
                path="interested_keywords",
                message=str(exc),
            ) from exc

    actor = await request.auser()
    logger.info(
        "Conference profile updated by admin.",
        actor=actor,
        user=user,
        conference=conference,
    )

    return await UserConferenceProfileService.load_profile_with_keywords(profile)

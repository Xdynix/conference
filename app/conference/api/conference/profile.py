from typing import Any

from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import Field, PatchDict, Schema
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    TrackRole,
    UserConferenceProfile,
)
from app.conference.services import ConferenceService, UserConferenceProfileService
from app.conference.types import KeywordText
from app.conference.types import (
    UserConferenceProfile as BaseUserConferenceProfileSchema,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import make_validation_error

from .core import prefetch_user_profile, router


class ProfileTrackRole(Schema):
    track: ULID
    role: TrackRole


class UserConferenceProfileResponse(BaseUserConferenceProfileSchema):
    conference_roles: list[ConferenceRole]
    track_roles: list[ProfileTrackRole]

    @staticmethod
    def resolve_interested_keywords(profile: UserConferenceProfile) -> list[str]:
        return [keyword.text for keyword in profile.interested_keywords.all()]

    @staticmethod
    def resolve_conference_roles(profile: UserConferenceProfile) -> list[str]:
        return [
            assignment.role
            for assignment in profile.user.prefetched_conference_roles  # type: ignore[attr-defined]
        ]

    @staticmethod
    def resolve_track_roles(profile: UserConferenceProfile) -> list[dict[str, Any]]:
        return [
            {"track": assignment.track.uid, "role": assignment.role}
            for assignment in profile.user.prefetched_track_roles  # type: ignore[attr-defined]
        ]


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
    return await prefetch_user_profile(profile, user)


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
    request: AuthedHttpRequest,
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
    actor = await request.auser()
    return await prefetch_user_profile(profile, actor)


class UserConferenceProfileSchema(BaseUserConferenceProfileSchema):
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
        user_uid=user.uid,
        conference_name=conference.name,
    )

    return await prefetch_user_profile(profile, user)


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
        actor_uid=actor.uid,
        user_uid=user.uid,
        conference_name=conference.name,
    )

    return await prefetch_user_profile(profile, actor)

from typing import Any

from django.shortcuts import aget_object_or_404
from ninja import Field, PatchDict, Schema
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
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


class FrontendContext(Schema):
    has_registrations: bool
    actionable_review_count: int


class UserConferenceProfileResponse(BaseUserConferenceProfileSchema):
    conference_roles: list[ConferenceRole]
    track_roles: list[ProfileTrackRole]
    context: FrontendContext

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

    @staticmethod
    def resolve_context(profile: UserConferenceProfile) -> FrontendContext:
        return FrontendContext(
            has_registrations=profile.has_registrations,  # type: ignore[attr-defined]
            actionable_review_count=profile.actionable_review_count,  # type: ignore[attr-defined]
        )


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
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    profile = await UserConferenceProfileService.get_or_create_profile(
        user=user,
        conference=conference,
    )
    return await prefetch_user_profile(profile, user)


@router.get(
    "/conferences/{slug:conference_name}/users/{ulid:user_uid}/profile",
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
    user_uid: ULID,
) -> UserConferenceProfile:
    """Return a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.active(),
        uid=user_uid,
    )

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
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
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

    await audit(
        request=request,
        action=AuditAction.USER_UPDATE_CONFERENCE_PROFILE,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_user_profile(profile, user)


@router.patch(
    "/conferences/{slug:conference_name}/users/{ulid:user_uid}/profile",
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
    user_uid: ULID,
    payload: PatchDict[UserConferenceProfileSchema],
) -> UserConferenceProfile:
    """Update a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.active(),
        uid=user_uid,
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

    await audit(
        request=request,
        action=AuditAction.USER_UPDATE_CONFERENCE_PROFILE,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        scope=conference.name,
        payload=payload,
    )

    actor = await request.auser()
    return await prefetch_user_profile(profile, actor)

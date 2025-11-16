from typing import Any

from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import PatchDict, Router
from ulid import ULID

from app.conference.models import UserProfile
from app.conference.schemas import Profile
from app.core.api.user.core import UserResponse
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest

router = Router(tags=["User Profile"], exclude_none=True)


async def patch_user_profile(user: User, payload: PatchDict[Profile]) -> bool:
    if not payload:
        return False
    profile, _ = await UserProfile.objects.aget_or_create(user=user)
    for attr, value in payload.items():
        setattr(profile, attr, value)
    await profile.asave(update_fields=list(payload.keys()))
    return True


@router.patch(
    "/users/me/profile",
    response=UserResponse,
    summary="Update My Profile",
    auth=is_authenticated,
)
async def update_current_user_profile(
    request: AuthedHttpRequest,
    payload: PatchDict[Profile],
) -> dict[str, Any]:
    """Update the current user's profile."""
    user = await request.auser()

    updated = await patch_user_profile(user, payload)

    if updated:
        logger.info("User updated profile.", user=user)

    return await user_response_registry.dump(user)


@router.patch(
    "/users/{ulid:user_id}/profile",
    response=UserResponse,
    summary="Update User Profile",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def update_user_profile(
    request: AuthedHttpRequest,
    user_id: ULID,
    payload: PatchDict[Profile],
) -> dict[str, Any]:
    """Update a user's profile by admin."""
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )

    updated = await patch_user_profile(user, payload)

    if updated:
        actor = await request.auser()
        logger.info("Admin updated user profile.", user=user, actor=actor)

    return await user_response_registry.dump(user)

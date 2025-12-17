from typing import Any

from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import PatchDict, Router
from ulid import ULID

from app.conference.models import Profile
from app.conference.types import Profile as ProfileSchema
from app.core.api.user.core import UserResponse
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest

router = Router(tags=["Profile"], exclude_none=True)


async def patch_profile(user: User, payload: PatchDict[ProfileSchema]) -> bool:
    if not payload:
        return False
    profile, _ = await Profile.objects.aget_or_create(user=user)
    for attr, value in payload.items():
        setattr(profile, attr, value)
    await profile.asave(update_fields=list(payload))
    return True


@router.patch(
    "/users/me/profile",
    response=UserResponse,
    summary="Update My Profile",
    auth=is_authenticated,
)
async def update_current_user_profile(
    request: AuthedHttpRequest,
    payload: PatchDict[ProfileSchema],
) -> dict[str, Any]:
    """Update the current user's profile."""
    user = await request.auser()

    await patch_profile(user, payload)

    logger.info("User updated profile.", user_uid=user.uid)

    return await user_response_registry.dump(user)


@router.patch(
    "/users/{ulid:uid}/profile",
    response=UserResponse,
    summary="Update Profile",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def update_profile(
    request: AuthedHttpRequest,
    uid: ULID,
    payload: PatchDict[ProfileSchema],
) -> dict[str, Any]:
    """Update a user's profile by admin."""
    user = await aget_object_or_404(
        User.objects.active(),
        uid=uid,
    )

    await patch_profile(user, payload)

    actor = await request.auser()
    logger.info(
        "Admin updated user profile.",
        user_uid=user.uid,
        actor_uid=actor.uid,
    )

    return await user_response_registry.dump(user)

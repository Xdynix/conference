from typing import Any

from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.core.auth import has_permissions, is_authenticated
from app.core.models import User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest

from .core import UserResponse, router


@router.get(
    "/users/me",
    response=UserResponse,
    summary="Get My Account",
    auth=is_authenticated,
)
async def get_current_user(request: AuthedHttpRequest) -> dict[str, Any]:
    """Retrieve the current user."""
    user = await request.auser()
    return await user_response_registry.dump(user)


@router.get(
    "/users/{ulid:user_id}",
    response=UserResponse,
    summary="Get User",
    auth=has_permissions(User.READ),
)
async def get_user(request: AuthedHttpRequest, user_id: ULID) -> dict[str, Any]:  # noqa: ARG001
    """Retrieve a single user."""
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )
    return await user_response_registry.dump(user)

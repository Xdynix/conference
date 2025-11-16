from collections.abc import Collection
from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import Field, Schema
from ulid import ULID

from app.core.auth import has_any_roles
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest

from .core import UserResponse, router


@transaction.atomic
def set_user_roles(user: User, roles: Collection[GlobalRole]) -> None:
    GlobalRoleAssignment.objects.filter(user=user).exclude(role__in=roles).delete()
    GlobalRoleAssignment.objects.bulk_create(
        [GlobalRoleAssignment(user=user, role=role) for role in roles],
        ignore_conflicts=True,
    )


class UpdateUserRolesRequest(Schema):
    roles: list[GlobalRole] = Field(max_length=len(GlobalRole))


@router.put(
    "/users/{ulid:user_id}/roles",
    response=UserResponse,
    summary="Update User Roles",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def update_user_roles(
    request: AuthedHttpRequest,
    user_id: ULID,
    payload: UpdateUserRolesRequest,
) -> dict[str, Any]:
    """Replace a user's global role assignments for any active account."""
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )
    roles = payload.roles

    await sync_to_async(set_user_roles)(user, roles)

    actor = await request.auser()
    logger.info("Admin updated user roles.", user=user, actor=actor, roles=roles)

    return await user_response_registry.dump(user)

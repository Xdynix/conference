from typing import Annotated, Any

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from ninja import Body, Field
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.services import UserService
from app.core.types import AuthedHttpRequest

from .core import UserResponse, router

UpdateUserRolesRequest = Annotated[
    list[GlobalRole],
    Field(max_length=len(GlobalRole)),
]


@router.put(
    "/users/{ulid:uid}/roles",
    response=UserResponse,
    summary="Update User Roles",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def update_user_roles(
    request: AuthedHttpRequest,
    uid: ULID,
    payload: Body[UpdateUserRolesRequest],
) -> dict[str, Any]:
    """Replace a user's global role assignments for any active account."""
    user = await aget_object_or_404(
        User.objects.active(),
        uid=uid,
    )

    await sync_to_async(UserService.set_roles)(user=user, roles=payload)

    await audit(
        request=request,
        action=AuditAction.USER_SET_ROLES,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        payload={"roles": payload},
    )

    return await user_response_registry.dump(user)

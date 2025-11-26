from http import HTTPStatus
from typing import Any

from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from ulid import ULID

from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.services import UserService
from app.core.services.user import UserIdentityConflict
from app.core.types import AuthedHttpRequest, EmailStr, Username
from app.ninja.errors import ErrorResponse
from app.verikit.types import VerifiedEmailStr

from .core import UserResponse, router


class UpdateCurrentUserRequest(Schema):
    username: Username | None = None
    email: VerifiedEmailStr | None = None


@router.patch(
    "/users/me",
    response={
        HTTPStatus.OK: UserResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Update My Account",
    auth=is_authenticated,
)
async def update_current_user(
    request: AuthedHttpRequest,
    payload: UpdateCurrentUserRequest,
) -> dict[str, Any]:
    """Update the current user's username and/or email.

    If email is being changed, provide a verification token obtained from the email
    verification flow. Managed users cannot update their username or email.
    """
    user = await request.auser()

    if user.managed:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Managed users cannot modify their username or email."),
        )

    try:
        user = await UserService.update_user(
            user=user,
            username=payload.username,
            email=payload.email,
        )
    except UserIdentityConflict as exc:
        message = _("A user with that username or email already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    logger.info("User updated account.", user_uid=user.uid)

    return await user_response_registry.dump(user)


class UpdateUserRequest(Schema):
    username: Username | None = None
    email: EmailStr | None = None


@router.patch(
    "/users/{ulid:user_id}",
    response={
        HTTPStatus.OK: UserResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Update User",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def update_user(
    request: AuthedHttpRequest,
    user_id: ULID,
    payload: UpdateUserRequest,
) -> dict[str, Any]:
    """Update a user's username and/or email by admin.

    Allows administrators to update the username and/or email for any active user except
    superusers because these fields are sensitive for account security (login credential
    and password recovery). Unlike the update current user endpoint, this does not
    require email verification and can update managed users.
    """
    user = await aget_object_or_404(
        User.objects.active().non_superuser(),
        uid=user_id,
    )

    try:
        user = await UserService.update_user(
            user=user,
            username=payload.username,
            email=payload.email,
        )
    except UserIdentityConflict as exc:
        message = _("A user with that username or email already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    actor = await request.auser()
    logger.info(
        "Admin updated user account.",
        user_uid=user.uid,
        actor_uid=actor.uid,
    )

    return await user_response_registry.dump(user)


# TODO: Logic for update `User.managed` field.

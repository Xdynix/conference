from http import HTTPStatus
from typing import Any

from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from ulid import ULID

from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest, EmailStr, Username
from app.ninja.errors import ErrorResponse
from app.verikit.types import VerifiedEmailStr

from .core import UserResponse, router


async def patch_user(
    user: User,
    username: Username | None,
    email: str | None,
) -> list[str]:
    """Update user's username and/or email.

    Args:
        user: The user to update.
        username: New username, or None to leave unchanged.
        email: New email, or None to leave unchanged.

    Returns:
        List of field names that were updated.

    Raises:
        HttpError: If username or email already exists (409 CONFLICT).
    """
    update_fields: list[str] = []

    if username is not None and username != user.username:
        user.username = username
        update_fields.append("username")

    if email is not None and (
        User.objects.normalize_email(email) != User.objects.normalize_email(user.email)
    ):
        user.email = email
        update_fields.append("email")

    if update_fields:
        try:
            await user.asave(update_fields=update_fields)
        except IntegrityError as exc:
            # Determine which field caused the conflict.
            if "username" in update_fields and "email" in update_fields:
                message = _("A user with that username or email already exists.")
            elif "username" in update_fields:
                message = _("A user with that username already exists.")
            else:
                message = _("A user with that email already exists.")

            raise HttpError(HTTPStatus.CONFLICT, message) from exc

    return update_fields


class UpdateCurrentUserRequest(Schema):
    username: Username | None = None
    email: VerifiedEmailStr | None = None


@router.patch(
    "/users/me",
    response={
        HTTPStatus.OK: UserResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
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
            HTTPStatus.FORBIDDEN,
            _("Managed users cannot modify their username or email."),
        )

    update_fields = await patch_user(user, payload.username, payload.email)
    if update_fields:
        logger.info("User updated account.", user=user, fields=update_fields)
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

    Allows administrators to update the username and/or email for any active,
    non-superuser user. Unlike the update current user endpoint, this does not
    require email verification and can update managed users.
    """
    user = await aget_object_or_404(
        User.objects.filter(is_active=True, is_superuser=False),
        uid=user_id,
    )

    update_fields = await patch_user(user, payload.username, payload.email)
    if update_fields:
        actor = await request.auser()
        logger.info(
            "Admin updated user account.",
            user=user,
            actor=actor,
            fields=update_fields,
        )
    return await user_response_registry.dump(user)


# TODO: Logic for update `User.managed` field.

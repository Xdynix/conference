from http import HTTPStatus

from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import ValidationError
from ulid import ULID

from app.core.auth import has_permissions, is_authenticated
from app.core.models import User
from app.core.types import AuthedHttpRequest, Password

from .core import aupdate_session_auth_hash, router, validate_password_for_user


class UpdateCurrentUserPasswordRequest(Schema):
    old_password: Password
    new_password: Password


@router.put(
    "/users/me/password",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Change My Password",
    auth=is_authenticated,
)
async def update_current_user_password(
    request: AuthedHttpRequest,
    payload: UpdateCurrentUserPasswordRequest,
) -> tuple[int, None]:
    """Change the current user's password.

    The user's session remains active after the password change.
    """
    user = await request.auser()
    old_password = payload.old_password
    new_password = payload.new_password

    if not await user.acheck_password(old_password.get_secret_value()):
        raise ValidationError(
            errors=[
                {
                    "type": "value_error",
                    "loc": ["body", "payload", "old_password"],
                    "msg": _("Invalid old password."),
                },
            ]
        )

    validate_password_for_user(new_password, user)

    logger.info("User changed password.", user=user)
    user.set_password(new_password.get_secret_value())
    await user.asave(update_fields=["password"])

    # Prevents the current session from being logged out.
    await aupdate_session_auth_hash(request, user)

    return HTTPStatus.NO_CONTENT, None


class UpdateUserPasswordRequest(Schema):
    new_password: Password


@router.put(
    "/users/{ulid:user_id}/password",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Change Password",
    auth=has_permissions(User.ADMIN),
)
async def update_user_password(
    request: AuthedHttpRequest,
    user_id: ULID,
    payload: UpdateUserPasswordRequest,
) -> tuple[int, None]:
    """Change a user's password by admin.

    Allows administrators to change the password for any active, non-superuser user.
    """
    user = await aget_object_or_404(
        User.objects.filter(is_active=True, is_superuser=False),
        uid=user_id,
    )
    new_password = payload.new_password

    validate_password_for_user(new_password, user)

    actor = await request.auser()
    logger.info("Admin changed user password.", user=user, actor=actor)
    user.set_password(new_password.get_secret_value())
    await user.asave(update_fields=["password"])

    return HTTPStatus.NO_CONTENT, None

from http import HTTPStatus

from django.contrib.auth import aupdate_session_auth_hash
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja import Schema
from ulid import ULID

from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.services import UserService
from app.core.services.user import InvalidPassword
from app.core.types import AuthedHttpRequest, Password
from app.ninja.errors import make_validation_error

from .core import router


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

    try:
        await UserService.change_password(
            user=user,
            old_password=payload.old_password.get_secret_value(),
            new_password=payload.new_password.get_secret_value(),
        )
    except ValueError as exc:
        raise make_validation_error(
            path="old_password",
            message=str(exc),
        ) from exc
    except InvalidPassword as exc:
        raise make_validation_error(
            path="new_password",
            message=exc.messages,
        ) from exc

    # Prevents the current session from being logged out.
    await aupdate_session_auth_hash(request, user)

    logger.info("User changed password.", user_uid=user.uid)

    return HTTPStatus.NO_CONTENT, None


class UpdateUserPasswordRequest(Schema):
    new_password: Password


@router.put(
    "/users/{ulid:user_id}/password",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Change Password",
    auth=has_any_roles(GlobalRole.ADMIN),
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
        User.objects.active().non_superuser(),
        uid=user_id,
    )

    try:
        await UserService.update_password(
            user=user,
            new_password=payload.new_password.get_secret_value(),
        )
    except InvalidPassword as exc:
        raise make_validation_error(
            path="new_password",
            message=exc.messages,
        ) from exc

    actor = await request.auser()
    logger.info(
        "Admin changed user password.",
        user_uid=user.uid,
        actor_uid=actor.uid,
    )

    return HTTPStatus.NO_CONTENT, None

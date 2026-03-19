from http import HTTPStatus

from django.contrib.auth import aupdate_session_auth_hash
from django.shortcuts import aget_object_or_404
from ninja import Schema, Status
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
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


@router.post(
    "/users/me:set-password",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Change My Password",
    auth=is_authenticated,
)
async def set_current_user_password(
    request: AuthedHttpRequest,
    payload: UpdateCurrentUserPasswordRequest,
) -> Status[None]:
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

    await audit(
        request=request,
        action=AuditAction.USER_SET_PASSWORD,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        payload=payload,
    )

    return Status(HTTPStatus.NO_CONTENT, None)


class UpdateUserPasswordRequest(Schema):
    new_password: Password


@router.post(
    "/users/{ulid:uid}:set-password",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Change Password",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def set_user_password(
    request: AuthedHttpRequest,
    uid: ULID,
    payload: UpdateUserPasswordRequest,
) -> Status[None]:
    """Change a user's password by admin.

    Allows administrators to change the password for any active, non-superuser user.
    """
    user = await aget_object_or_404(
        User.objects.active().non_superuser(),
        uid=uid,
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

    await audit(
        request=request,
        action=AuditAction.USER_SET_PASSWORD,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        payload=payload,
    )

    return Status(HTTPStatus.NO_CONTENT, None)

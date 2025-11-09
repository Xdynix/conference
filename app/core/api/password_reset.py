from http import HTTPStatus
from typing import Annotated

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext as _
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from pydantic import StringConstraints
from ulid import ULID

from app.core.api.user.core import validate_password_for_user
from app.core.models import User
from app.core.services import PasswordResetService
from app.core.types import EmailStr, HttpRequest, Password
from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.throttling import AnonThrottle, throttling

router = Router(tags=["Password Reset"], exclude_none=True)


class CreatePasswordResetRequest(Schema):
    email: EmailStr


class CreatePasswordResetResponse(Schema):
    pass


@router.post(
    "/password-resets",
    response={
        HTTPStatus.CREATED: CreatePasswordResetResponse,
        HTTPStatus.TOO_MANY_REQUESTS: ErrorResponse,
    },
    summary="Request Password Reset",
)
@decorate_view(throttling(AnonThrottle("100/min")))
@decorate_view(cf_turnstile_required)
async def create_password_reset(
    request: HttpRequest,
    payload: CreatePasswordResetRequest,
) -> tuple[int, CreatePasswordResetResponse] | JsonResponse:
    """Request a password reset token for a user account.

    Initiates the password reset process by sending an email with a reset token to the
    user's registered email address. The email is only sent if a user with the provided
    email exists, is active, and has a usable password.

    Returns 429 if a reset token was recently issued for this user.
    """
    user = await User.objects.filter(is_active=True, email=payload.email).afirst()
    # Users without a usable password are considered to be authenticated by external
    # services (such as OIDC). Currently, this system does not implement such
    # authentication, but is reserved for future expansion.
    if user is not None and user.has_usable_password():
        result = await PasswordResetService.create_token(user, request)
        if result is None:
            message = _("A password reset token was recently issued for this user.")
            interval_seconds = int(
                settings.PASSWORD_RESET_TOKEN_INTERVAL.total_seconds()
            )
            return JsonResponse(
                ErrorResponse(message=message).model_dump(),
                status=HTTPStatus.TOO_MANY_REQUESTS,
                headers={"Retry-After": str(interval_seconds)},
            )
    return HTTPStatus.CREATED, CreatePasswordResetResponse()


class ConsumePasswordResetRequest(Schema):
    user_id: ULID
    token: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    new_password: Password


class ConsumePasswordResetResponse(Schema):
    pass


@router.post(
    "/password-resets:consume",
    response={
        HTTPStatus.OK: ConsumePasswordResetResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Reset Password",
)
async def consume_password_reset(
    request: HttpRequest,  # noqa: ARG001
    payload: ConsumePasswordResetRequest,
) -> ConsumePasswordResetResponse:
    """Reset a user's password using a valid password reset token.

    Consumes a password reset token and sets a new password for the user account. The
    token must be valid, not expired, and not already used. After successfully resetting
    the password, all other active tokens for the user are invalidated.

    Returns 422 if the token is invalid, expired, or already used.
    """
    error_msg = _("Invalid or expired password reset token.")

    user = await User.objects.filter(is_active=True, uid=payload.user_id).afirst()
    if user is None:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, error_msg)

    token = payload.token
    new_password = payload.new_password

    validate_password_for_user(new_password, user)

    if not await PasswordResetService.consume_token(user, token, new_password):
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, error_msg)

    return ConsumePasswordResetResponse()

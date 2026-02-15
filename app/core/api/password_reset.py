from http import HTTPStatus
from typing import Annotated

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from pydantic import SecretStr, StringConstraints
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.core.models import User
from app.core.services import PasswordResetService
from app.core.types import EmailStr, HttpRequest, Password
from app.ninja.errors import ErrorResponse, make_validation_error
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
    user = await User.objects.active().filter(email=payload.email).afirst()
    # Users without a usable password are considered to be authenticated by external
    # services (such as OIDC). Currently, this system does not implement such
    # authentication, but is reserved for future expansion.
    if user is not None and user.has_usable_password():
        if settings.PASSWORD_RESET_PAGE_URL:
            path = settings.PASSWORD_RESET_PAGE_URL
        elif settings.PASSWORD_RESET_PAGE_URL_NAME:
            path = reverse(settings.PASSWORD_RESET_PAGE_URL_NAME)
        else:
            path = reverse("core:password-reset")
        password_reset_page_url = request.build_absolute_uri(path)
        result = await sync_to_async(PasswordResetService.create_token)(
            user,
            password_reset_page_url=password_reset_page_url,
        )
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

        await audit(
            request=request,
            action=AuditAction.USER_REQUEST_PASSWORD_RESET,
            resource=AuditResource.USER,
            resource_id=str(user.uid),
            resource_label=user.email or user.username,
            payload=payload,
        )

    return HTTPStatus.CREATED, CreatePasswordResetResponse()


class ConsumePasswordResetRequest(Schema):
    user: ULID
    token: Annotated[
        SecretStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    new_password: Password


@router.post(
    "/password-resets:consume",
    response={
        HTTPStatus.NO_CONTENT: None,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Reset Password",
)
async def consume_password_reset(
    request: HttpRequest,
    payload: ConsumePasswordResetRequest,
) -> tuple[int, None]:
    """Reset a user's password using a valid password reset token.

    Consumes a password reset token and sets a new password for the user account. The
    token must be valid, not expired, and not already used. After successfully resetting
    the password, all other active tokens for the user are invalidated.

    Returns 400 if the token is invalid, expired, or already used.
    """
    error_msg = _("Invalid or expired password reset token.")

    try:
        user = await User.objects.active().aget(uid=payload.user)
    except User.DoesNotExist as exc:
        # Returns the same response as invalid token path to avoid leaking user
        # existence.
        await audit(
            request=request,
            action=AuditAction.USER_RESET_PASSWORD_FAILED,
            resource=AuditResource.USER,
            resource_id=str(payload.user),
            payload=payload,
        )
        raise HttpError(HTTPStatus.BAD_REQUEST, error_msg) from exc

    token = payload.token
    new_password = payload.new_password

    try:
        validate_password(new_password.get_secret_value(), user=user)
    except ValidationError as exc:
        raise make_validation_error(path="new_password", message=exc.messages) from exc

    if not await sync_to_async(PasswordResetService.consume_token)(
        user,
        token,
        new_password,
    ):
        await audit(
            request=request,
            action=AuditAction.USER_RESET_PASSWORD_FAILED,
            resource=AuditResource.USER,
            resource_id=str(user.uid),
            resource_label=user.email or user.username,
            payload=payload,
        )
        raise HttpError(HTTPStatus.BAD_REQUEST, error_msg)

    await audit(
        request=request,
        action=AuditAction.USER_RESET_PASSWORD,
        resource=AuditResource.USER,
        resource_id=str(user.uid),
        resource_label=user.email or user.username,
        payload=payload,
    )

    return HTTPStatus.NO_CONTENT, None

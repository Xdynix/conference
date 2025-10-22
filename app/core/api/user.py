from http import HTTPStatus
from typing import Annotated, Literal, assert_never, cast

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError, ValidationError
from ulid import ULID

from app.core.auth import has_permissions, is_authenticated
from app.core.models import User
from app.core.schemas import User as UserSchema
from app.core.types import EmailStr, HttpRequest, Password, Username
from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.throttling import AnonThrottle, throttling
from app.verikit.types import VerifiedEmailStr


async def aupdate_session_auth_hash(
    request: HttpRequest,
    user: User,
) -> None:  # pragma: no cover
    # Bugfix for `django.contrib.auth.aupdate_session_auth_hash`.
    # TODO: Remove after django/django#19749 (Django #36561) released.
    from django.contrib.auth import HASH_SESSION_KEY

    await request.session.acycle_key()
    if hasattr(user, "get_session_auth_hash") and await request.auser() == user:
        await request.session.aset(HASH_SESSION_KEY, user.get_session_auth_hash())


router = Router(tags=["User"], exclude_none=True)


class ResolveUserByUsernameRequest(Schema):
    by: Literal["username"]
    username: Username


class ResolveUserByEmailRequest(Schema):
    by: Literal["email"]
    email: EmailStr


ResolveUserRequest = Annotated[
    ResolveUserByUsernameRequest | ResolveUserByEmailRequest,
    Field(discriminator="by"),
]


class ResolveUserResponse(Schema):
    uid: ULID | None


@router.post(
    "/users:resolve",
    response=ResolveUserResponse,
    summary="Resolve User UID",
    auth=has_permissions(User.READ),
)
async def resolve_user(
    request: HttpRequest,  # noqa: ARG001
    payload: ResolveUserRequest,
) -> ResolveUserResponse:
    """Resolve a user identifier to a ULID.

    Converts a natural user identifier (`username` or `email`) into the user's immutable
    UID. The request specifies the identifier type in the `by` field and provides
    exactly one corresponding value. Useful for translating login-style identifiers into
    stable IDs for use in other API requests.
    """
    match payload:
        case ResolveUserByUsernameRequest():
            query = User.objects.filter(is_active=True, username=payload.username)
        case ResolveUserByEmailRequest():
            query = User.objects.filter(is_active=True, email__iexact=payload.email)
        case _ as unreachable:
            assert_never(unreachable)

    try:
        user = await query.values("uid").aget()
    except User.DoesNotExist:
        return ResolveUserResponse(uid=None)
    except User.MultipleObjectsReturned:  # pragma: no cover
        logger.error(
            "Resolve user got multiple results, which should never happen.",
            payload=payload,
        )
        raise

    return ResolveUserResponse(uid=user["uid"])


class CreateRegistrationRequest(Schema):
    username: Username
    email: VerifiedEmailStr
    password: Password


@router.post(
    "/registrations",
    response={
        HTTPStatus.CREATED: UserSchema,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Register",
)
@decorate_view(throttling(AnonThrottle("20/min")))
@decorate_view(cf_turnstile_required)
async def create_registration(
    request: HttpRequest,  # noqa: ARG001
    payload: CreateRegistrationRequest,
) -> tuple[int, User]:
    """Create a new user registration.

    Registers a new user account with the provided username, verified email, and
    password. The email must be verified using a token obtained from the email
    verification flow.
    """
    # Create a temporary user to validate password.
    temp_user = User(username=payload.username, email=payload.email)
    validate_password_for_user(payload.password, temp_user, field_name="password")

    try:
        user = await User.objects.acreate_user(
            username=payload.username,
            email=payload.email,
            password=payload.password.get_secret_value(),
        )
    except IntegrityError as exc:
        message = _("A user with that username or email already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    logger.info("User registered.", user=user)
    return HTTPStatus.CREATED, user


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
        HTTPStatus.OK: UserSchema,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
    },
    summary="Update My Account",
    auth=is_authenticated,
)
async def update_current_user(
    request: HttpRequest,
    payload: UpdateCurrentUserRequest,
) -> User:
    """Update the current user's username and/or email.

    If email is being changed, provide a verification token obtained from the email
    verification flow. Managed users cannot update their username or email.
    """
    user = cast(User, await request.auser())

    if user.managed:
        raise HttpError(
            HTTPStatus.FORBIDDEN,
            _("Managed users cannot modify their username or email."),
        )

    update_fields = await patch_user(user, payload.username, payload.email)
    if update_fields:
        logger.info("User updated account.", user=user, fields=update_fields)
    return user


class UpdateUserRequest(Schema):
    username: Username | None = None
    email: EmailStr | None = None


@router.patch(
    "/users/{ulid:user_id}",
    response={
        HTTPStatus.OK: UserSchema,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Update User",
    auth=has_permissions(User.ADMIN),
)
async def update_user(
    request: HttpRequest,
    user_id: ULID,
    payload: UpdateUserRequest,
) -> User:
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
        actor = cast(User, await request.auser())
        logger.info(
            "Admin updated user account.",
            user=user,
            actor=actor,
            fields=update_fields,
        )
    return user


def validate_password_for_user(
    new_password: Password,
    user: User,
    field_name: str = "new_password",
) -> None:
    """Validate a password and convert any errors to Pydantic format."""
    try:
        validate_password(new_password.get_secret_value(), user=user)
    except DjangoValidationError as exc:
        raise ValidationError(
            errors=[
                {
                    "type": "value_error",
                    "loc": ["body", "payload", field_name],
                    "msg": message,
                }
                for message in exc.messages
            ]
        ) from exc


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
    request: HttpRequest,
    payload: UpdateCurrentUserPasswordRequest,
) -> tuple[int, None]:
    """Change the current user's password.

    The user's session remains active after the password change.
    """
    user = cast(User, await request.auser())
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
    request: HttpRequest,
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

    actor = cast(User, await request.auser())
    logger.info("Admin changed user password.", user=user, actor=actor)
    user.set_password(new_password.get_secret_value())
    await user.asave(update_fields=["password"])

    return HTTPStatus.NO_CONTENT, None

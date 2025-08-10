from http import HTTPStatus
from typing import Annotated, Literal, assert_never, cast

from django.contrib.auth import aupdate_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, Router, Schema
from ninja.errors import ValidationError
from ulid import ULID

from app.core.auth import has_permissions, is_authenticated
from app.core.models import User
from app.core.types import EmailStr, HttpRequest, Password, Username

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
)
@has_permissions(User.READ)
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


def validate_password_for_user(new_password: Password, user: User) -> None:
    """Validate a password and convert any errors to Pydantic format."""
    try:
        validate_password(new_password.get_secret_value(), user=user)
    except DjangoValidationError as exc:
        raise ValidationError(
            errors=[
                {
                    "type": "value_error",
                    "loc": ["body", "payload", "new_password"],
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
)
@is_authenticated
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

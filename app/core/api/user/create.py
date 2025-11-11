from http import HTTPStatus
from typing import Any, Literal

from asgiref.sync import sync_to_async
from django.contrib.auth import alogin
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from app.core.api.session import Session, clean_request_user_cache
from app.core.auth import has_permissions
from app.core.models import User
from app.core.registry.create_user import create_user_registry
from app.core.registry.user_response import user_response_registry
from app.core.types import AuthedHttpRequest, EmailStr, HttpRequest, Password, Username
from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.throttling import AnonThrottle, throttling
from app.verikit.types import VerifiedEmailStr

from .core import UserResponse, router, validate_password_for_user


@sync_to_async
@transaction.atomic
def create_new_user(
    username: Username,
    email: str,
    password: Password,
    managed: bool,
    payload: Any,
) -> User:
    # Create a temporary user to validate password.
    temp_user = User(username=username, email=email)
    validate_password_for_user(password, temp_user, field_name="password")

    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password.get_secret_value(),
            managed=managed,
        )
    except IntegrityError as exc:
        message = _("A user with that username or email already exists.")
        raise HttpError(HTTPStatus.CONFLICT, message) from exc

    create_user_registry.dispatch(user, payload)

    return user


class BaseCreateRegistrationRequest(Schema):
    username: Username
    email: VerifiedEmailStr
    password: Password


CreateRegistrationRequest = create_user_registry.extend_schema(
    BaseCreateRegistrationRequest,
    "CreateRegistrationRequest",
)


@router.post(
    "/registrations",
    response={
        HTTPStatus.CREATED: Session,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Register",
)
@decorate_view(throttling(AnonThrottle("20/min")))
@decorate_view(cf_turnstile_required)
async def create_registration(
    request: HttpRequest,
    payload: CreateRegistrationRequest,  # type: ignore[valid-type]
) -> tuple[int, Session]:
    """Create a new user registration and log them in.

    Registers a new user account with the provided username, verified email, and
    password. The email must be verified using a token obtained from the email
    verification flow. Upon successful registration, the user is automatically logged in
    and a session is created.
    """
    user = await create_new_user(
        username=payload.username,  # type: ignore[attr-defined]
        email=payload.email,  # type: ignore[attr-defined]
        password=payload.password,  # type: ignore[attr-defined]
        managed=False,
        payload=payload,
    )
    await alogin(request, user)
    clean_request_user_cache(request)
    logger.info("User registered and logged in.", user=user)
    return HTTPStatus.CREATED, await Session.from_request(request)


class BaseCreateUserRequest(Schema):
    username: Username
    email: EmailStr | Literal[""] = ""
    password: Password
    managed: bool = False


CreateUserRequest = create_user_registry.extend_schema(
    BaseCreateUserRequest,
    "CreateUserRequest",
)


@router.post(
    "/users",
    response={
        HTTPStatus.CREATED: UserResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
    },
    summary="Create User",
    auth=has_permissions(User.WRITE),
)
async def create_user(
    request: AuthedHttpRequest,
    payload: CreateUserRequest,  # type: ignore[valid-type]
) -> tuple[int, dict[str, Any]]:
    """Create a new user account by admin.

    Allows administrators with write permission to create user accounts. Unlike the
    registration endpoint, this does not require email verification.
    """
    user = await create_new_user(
        username=payload.username,  # type: ignore[attr-defined]
        email=payload.email,  # type: ignore[attr-defined]
        password=payload.password,  # type: ignore[attr-defined]
        managed=payload.managed,  # type: ignore[attr-defined]
        payload=payload,
    )
    actor = await request.auser()
    logger.info("Admin created user.", user=user, actor=actor)
    return HTTPStatus.CREATED, await user_response_registry.dump(user)

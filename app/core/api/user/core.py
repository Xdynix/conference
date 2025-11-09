from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Router
from ninja.errors import ValidationError

from app.core.models import User
from app.core.registry.user_response import user_response_registry
from app.core.types import HttpRequest, Password

router = Router(tags=["User"], exclude_none=True)


UserResponse = user_response_registry.get_schema()


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


def validate_password_for_user(
    new_password: Password,
    user: User,
    field_name: str = "new_password",
) -> None:
    """Validate a password and convert any errors to Pydantic format."""
    try:
        django_validate_password(new_password.get_secret_value(), user=user)
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

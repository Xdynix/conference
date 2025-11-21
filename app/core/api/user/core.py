from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Router
from ninja.errors import ValidationError

from app.core.models import User
from app.core.registry.user_response import user_response_registry
from app.core.types import Password

router = Router(tags=["User"], exclude_none=True)


UserResponse = user_response_registry.get_schema()


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

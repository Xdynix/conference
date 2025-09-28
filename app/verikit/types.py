__all__ = (
    "EmailStr",
    "VerifiedEmailStr",
)


from typing import Annotated

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from pydantic import AfterValidator, StringConstraints, TypeAdapter
from pydantic import EmailStr as DefaultEmailStr

from app.verikit.services import EmailVerificationService

EmailStr = Annotated[
    DefaultEmailStr,
    AfterValidator(get_user_model().objects.normalize_email),
]

email_str_adapter = TypeAdapter(EmailStr)


def verify_email_token(token: str) -> EmailStr:
    email = EmailVerificationService.verify_token(token)
    if email is None:
        message = _("Invalid or expired verification token for this email address.")
        raise ValueError(message)
    return email_str_adapter.validate_python(email)


VerifiedEmailStr = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2048),
    AfterValidator(verify_email_token),
]

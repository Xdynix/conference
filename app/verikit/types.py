from typing import Annotated, Self

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from pydantic import AfterValidator, BaseModel, StringConstraints, model_validator
from pydantic import EmailStr as DefaultEmailStr

from app.verikit.services import EmailVerificationService

EmailStr = Annotated[
    DefaultEmailStr,
    AfterValidator(get_user_model().objects.normalize_email),
]
Token = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2048),
]


class VerifiedEmail(BaseModel):
    """A validated email address with verification token."""

    email: EmailStr
    token: Token

    @model_validator(mode="after")
    def check_email_token(self) -> Self:
        if not EmailVerificationService.verify_token(self.email, self.token):
            message = _("Invalid or expired verification token for this email address.")
            raise ValueError(message)
        return self

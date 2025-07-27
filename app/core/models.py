from typing import ClassVar, override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from app.utils.models import ULIDModel


class UserManager(DjangoUserManager["User"]):
    @classmethod
    @override
    def normalize_email(cls, email: str | None) -> str:
        """Normalizes the email address by lower-casing it.

        Although theoretically the name part of the email is case-sensitive,
        almost all modern mailboxes ignore its case.

        Another special case is when the email address contains special characters,
        this method may not return the expected value. However, this type of address
        has not yet received widespread support (as of 2025), so it will not be
        considered for the time being.
        """
        email = email or ""
        return email.lower()


class User(ULIDModel, AbstractUser):
    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = (
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="unique_non_empty_email",
                violation_error_code="unique",
                violation_error_message=_("A user with that email already exists."),
            ),
        )

    @property
    def given_name(self) -> str:
        """Alias for the first name."""
        return self.first_name

    @given_name.setter
    def given_name(self, given_name: str) -> None:
        self.first_name = given_name

    @property
    def family_name(self) -> str:
        """Alias for the last name."""
        return self.last_name

    @family_name.setter
    def family_name(self, family_name: str) -> None:
        self.last_name = family_name

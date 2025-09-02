from typing import ClassVar, override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel
from app.utils.perm import Perm


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

    READ = Perm()
    ADMIN = Perm()

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


class Permission(models.Model):
    key = models.CharField(_("key"), max_length=255, primary_key=True)

    class Meta:
        verbose_name = _("permission")
        verbose_name_plural = _("permissions")

    def __str__(self) -> str:
        return self.key


class AbstractRole(models.Model):
    name = models.CharField(
        _("name"),
        max_length=255,
        primary_key=True,
        help_text=_(
            "Unique identifier for the role (e.g., 'admin', 'user', 'viewer')."
        ),
    )
    display_name = models.CharField(
        _("display name"),
        max_length=255,
        unique=True,
        help_text=_("Human-readable name for the role."),
    )
    description = models.TextField(
        _("description"),
        blank=True,
        default="",
        help_text=_("Description of the role."),
    )
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        verbose_name=_("permissions"),
        help_text=_("Permissions granted to users with this role."),
    )

    class Meta:
        abstract = True


class Role(AbstractRole):
    class Meta(AbstractRole.Meta):
        verbose_name = _("role")
        verbose_name_plural = _("roles")

    def __str__(self) -> str:
        return self.name


class AbstractRoleAssignment(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name=_("user"))

    class Meta:
        abstract = True


class RoleAssignment(AbstractRoleAssignment):
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="assignments",
        related_query_name="assignment",
        verbose_name=_("role"),
    )

    class Meta:
        verbose_name = _("role assignment")
        verbose_name_plural = _("role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "role"),
                name="unique_user_role",
                violation_error_code="unique",
                violation_error_message=_("The role assignment already exists."),
            ),
        )
        indexes = (models.Index(fields=("role",)),)

    def __str__(self) -> str:
        return f"{self.role}: {self.user}"


class PasswordResetToken(models.Model):
    """Represents an email password reset token.

    Multiple active tokens can exist for the same user.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
        related_query_name="password_reset_token",
        verbose_name=_("user"),
    )
    token_hash = models.CharField(
        _("token hash"),
        max_length=64,
        unique=True,
        help_text=_("Hashed password reset token for secure storage."),
    )
    create_time = models.DateTimeField(_("create time"), auto_now_add=True)
    expire_time = models.DateTimeField(_("expire time"))
    consume_time = models.DateTimeField(
        _("consume time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("When this token was consumed for password reset."),
    )

    class Meta:
        verbose_name = _("password reset token")
        verbose_name_plural = _("password reset tokens")
        indexes = (
            # For service queries (active tokens + rate limiting).
            models.Index(fields=("user", "create_time")),
            models.Index(fields=("user", "expire_time", "consume_time", "token_hash")),
            # For admin default list ordering.
            models.Index(fields=("create_time",)),
            # For cleanup jobs by expiration time.
            models.Index(fields=("expire_time",)),
        )

    def __str__(self) -> str:
        status = _("consumed") if self.consume_time else _("pending")
        return f"{self.user} ({status})"

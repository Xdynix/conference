from typing import ClassVar, Self, override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.sessions.models import Session
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel


class GlobalRole(models.TextChoices):
    ADMIN = "Admin", _("Admin")
    READ_ALL = "Read All", _("Read All")


class UserQuerySet(models.QuerySet["User"]):
    def active(self) -> Self:
        return self.filter(is_active=True)

    def non_superuser(self) -> Self:
        return self.filter(is_superuser=False)


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

    def get_queryset(self) -> UserQuerySet:
        return UserQuerySet(self.model, using=self._db)

    def active(self) -> UserQuerySet:
        return self.get_queryset().active()


class User(ULIDModel, AbstractUser):
    managed = models.BooleanField(
        _("managed"),
        default=False,
        help_text=_(
            "Designates whether this user is controlled by the system. "
            "Managed users cannot modify their username and email."
        ),
    )

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


class GlobalRoleAssignment(TimeStampedModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="global_role_assignments",
        related_query_name="global_role_assignment",
        verbose_name=_("user"),
    )
    role = models.CharField(_("role"), max_length=255, choices=GlobalRole)

    class Meta:
        verbose_name = _("global role assignment")
        verbose_name_plural = _("global role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "role"),
                name="unique_global_role_assignment",
                violation_error_code="unique",
                violation_error_message=_("The role assignment already exists."),
            ),
            models.CheckConstraint(
                name="global_role_assignment_role_value",
                condition=Q(role__in=GlobalRole.values),
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


class ApiKey(models.Model):
    """Hashed API key for programmatic access to the REST API.

    At most one active (non-revoked) key exists per user. Revoked keys are retained for
    audit history.
    """

    KEY_PREFIX = "cfk_"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
        related_query_name="api_key",
        verbose_name=_("user"),
    )
    hashed_key = models.CharField(_("hashed key"), max_length=64, unique=True)
    auth_hash = models.CharField(
        _("auth hash"),
        max_length=64,
        help_text=_(
            "Snapshot of the user's session auth hash at key creation time. "
            "Used to detect password changes."
        ),
    )
    create_time = models.DateTimeField(_("create time"), auto_now_add=True)
    last_use_time = models.DateTimeField(
        _("last use time"),
        null=True,
        blank=True,
        default=None,
    )
    revoke_time = models.DateTimeField(
        _("revoke time"),
        null=True,
        blank=True,
        default=None,
    )

    class Meta:
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")
        constraints = (
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(revoke_time__isnull=True),
                name="one_active_api_key_per_user",
            ),
        )
        indexes = (models.Index(fields=("user", "revoke_time")),)

    def __str__(self) -> str:
        status = _("active") if self.revoke_time is None else _("revoked")
        return f"{self.user} ({status})"


class ApiKeySession(models.Model):
    """Links an API key to the Django session it created for revocation tracking."""

    api_key = models.OneToOneField(
        ApiKey,
        on_delete=models.CASCADE,
        related_name="session_link",
        verbose_name=_("API key"),
    )
    session = models.OneToOneField(
        Session,
        on_delete=models.CASCADE,
        related_name="api_key_link",
        verbose_name=_("session"),
    )
    create_time = models.DateTimeField(_("create time"), auto_now_add=True)

    class Meta:
        verbose_name = _("API key session")
        verbose_name_plural = _("API key sessions")

    def __str__(self) -> str:
        return str(self.api_key)

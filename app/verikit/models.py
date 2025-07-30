from django.db import models
from django.utils.translation import gettext_lazy as _


class EmailVerification(models.Model):
    """Represents a verification code sent to an email address.

    Multiple active verifications can exist for the same email address.
    """

    email = models.EmailField(_("email address"))
    code_salt = models.BinaryField(
        _("code salt"),
        help_text=_("Random salt used for hashing the verification code."),
    )
    code_hash = models.BinaryField(
        _("code hash"),
        help_text=_("Hashed verification code for secure storage."),
    )
    create_time = models.DateTimeField(_("create time"), auto_now_add=True)
    expire_time = models.DateTimeField(_("expire time"))
    verify_time = models.DateTimeField(
        _("verify time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("When this code was successfully verified."),
    )

    class Meta:
        verbose_name = _("email verification")
        verbose_name_plural = _("email verifications")
        indexes = (
            # For service queries (active verifications + rate limiting).
            models.Index(fields=("email", "expire_time", "verify_time", "create_time")),
            # For admin email search with ordering.
            models.Index(fields=("email", "create_time")),
            # For admin default list ordering.
            models.Index(fields=("create_time",)),
            # For cleanup jobs by expiration time.
            models.Index(fields=("expire_time",)),
        )

    def __str__(self) -> str:
        status = _("verified") if self.verify_time else _("pending")
        return f"{self.email} ({status})"

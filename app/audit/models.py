from django.db import models
from django.db.models.functions import Now
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    timestamp = models.DateTimeField(_("timestamp"), db_default=Now())

    actor_uid = models.CharField(_("actor UID"), max_length=26, blank=True, default="")
    actor_label = models.CharField(
        _("actor label"),
        max_length=255,
        blank=True,
        default="",
    )

    action = models.CharField(_("action"), max_length=128)

    resource = models.CharField(_("resource"), max_length=64)
    resource_id = models.CharField(
        _("resource ID"),
        max_length=255,
        blank=True,
        default="",
    )
    resource_label = models.CharField(
        _("resource label"),
        max_length=255,
        blank=True,
        default="",
    )

    scope = models.CharField(
        _("scope"),
        max_length=255,
        blank=True,
        default="",
    )

    payload = models.JSONField(_("payload"), default=dict, blank=True)

    detail = models.JSONField(_("detail"), default=dict, blank=True)

    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    request_id = models.CharField(
        _("request ID"),
        max_length=64,
        blank=True,
        default="",
    )

    class Meta:
        verbose_name = _("audit log")
        verbose_name_plural = _("audit logs")
        indexes = (
            models.Index(fields=("timestamp",)),
            models.Index(fields=("action",)),
            models.Index(fields=("scope", "timestamp")),
            models.Index(fields=("scope", "resource", "resource_id")),
            models.Index(fields=("resource", "resource_id")),
            models.Index(fields=("actor_uid", "timestamp")),
        )
        ordering = ("-timestamp",)

    def __str__(self) -> str:
        return (
            f"{self.timestamp} {self.action} by "
            f"{self.actor_label or self.actor_uid or 'anonymous'}"
        )

from django.db import models
from django.utils.translation import gettext_lazy as _

from app.audit.types import Auditable, AuditResource, AuditResourceInfo
from app.core.models import User
from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference


class EmailSendLog(Auditable, TimeStampedModel, ULIDModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="email_send_logs",
        related_query_name="email_send_log",
        verbose_name=_("conference"),
    )
    correlation_id = models.CharField(
        _("correlation ID"),
        max_length=255,
        help_text=_(
            "Caller-defined identifier for idempotency and log correlation "
            "(e.g. 'acceptance-letter:{paper_uid}')."
        ),
    )
    send_time = models.DateTimeField(
        _("send time"),
        help_text=_("When the email was last sent (updated on forced resend)."),
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="email_send_logs",
        related_query_name="email_send_log",
        verbose_name=_("sender"),
    )

    class Meta:
        verbose_name = _("email send log")
        verbose_name_plural = _("email send logs")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "correlation_id"),
                name="unique_email_send_log_correlation",
                violation_error_code="unique",
                violation_error_message=_(
                    "A send log with this correlation ID already exists "
                    "for this conference."
                ),
            ),
        )

    def __str__(self) -> str:
        return self.correlation_id

    def audit_resource_info(self) -> AuditResourceInfo:
        return AuditResourceInfo(
            resource=AuditResource.EMAIL,
            resource_id=self.correlation_id,
            resource_label=self.correlation_id,
        )

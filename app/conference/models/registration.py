from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import ULIDModel

from .conference import Conference


class AttendanceType(ULIDModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="attendance_types",
        related_query_name="attendance_type",
        verbose_name=_("conference"),
    )
    display_name = models.CharField(_("display name"), max_length=255)
    ordering = models.IntegerField(
        _("ordering"),
        default=0,
        help_text=_("Determines the display order of attendance types."),
    )
    admin_only = models.BooleanField(
        _("admin only"),
        default=True,
        help_text=_(
            "If true, this option is hidden from registrants and can only be "
            "assigned by administrators."
        ),
    )
    paper_required = models.BooleanField(
        _("paper required"),
        default=True,
        help_text=_(
            "If true, this option only appears when the registrant selects a paper."
        ),
    )

    class Meta:
        verbose_name = _("attendance type")
        verbose_name_plural = _("attendance types")
        ordering = ("ordering", "display_name")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "display_name"),
                name="unique_attendance_type_display_name",
                violation_error_code="unique",
                violation_error_message=_(
                    "An attendance type with this name already exists "
                    "for this conference."
                ),
            ),
        )

    def __str__(self) -> str:
        return self.display_name

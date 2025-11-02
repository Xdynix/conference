from django.db import models
from django.utils.translation import gettext_lazy as _

from app.core.models import AbstractRole, AbstractRoleAssignment

from .conference import Conference, Track


class ConferenceRole(AbstractRole):
    class Meta(AbstractRole.Meta):
        verbose_name = _("conference role")
        verbose_name_plural = _("conference roles")

    def __str__(self) -> str:
        return self.name


class ConferenceRoleAssignment(AbstractRoleAssignment):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        related_query_name="role_assignment",
        verbose_name=_("conference"),
    )
    role = models.ForeignKey(
        ConferenceRole,
        on_delete=models.CASCADE,
        related_name="assignments",
        related_query_name="assignment",
        verbose_name=_("role"),
    )

    class Meta:
        verbose_name = _("conference role assignment")
        verbose_name_plural = _("conference role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "user", "role"),
                name="unique_conference_user_role",
                violation_error_code="unique",
                violation_error_message=_(
                    "The conference role assignment already exists."
                ),
            ),
        )
        indexes = (
            models.Index(fields=("user", "role")),
            models.Index(fields=("role",)),
        )

    def __str__(self) -> str:
        return f"[{self.conference}] {self.role}: {self.user}"


class TrackRole(AbstractRole):
    class Meta(AbstractRole.Meta):
        verbose_name = _("track role")
        verbose_name_plural = _("track roles")

    def __str__(self) -> str:
        return self.name


class TrackRoleAssignment(AbstractRoleAssignment):
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        related_query_name="role_assignment",
        verbose_name=_("track"),
    )
    role = models.ForeignKey(
        TrackRole,
        on_delete=models.CASCADE,
        related_name="assignments",
        related_query_name="assignment",
        verbose_name=_("role"),
    )

    class Meta:
        verbose_name = _("track role assignment")
        verbose_name_plural = _("track role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("track", "user", "role"),
                name="unique_track_user_role",
                violation_error_code="unique",
                violation_error_message=_("The track role assignment already exists."),
            ),
        )
        indexes = (
            models.Index(fields=("user", "role")),
            models.Index(fields=("role",)),
        )

    def __str__(self) -> str:
        return f"[{self.track}] {self.role}: {self.user}"

from collections.abc import Sequence

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel

from .conference import Conference, Track

User = get_user_model()


class ConferenceRole(models.TextChoices):
    CHAIR = "Chair", _("Chair")
    SECRETARY = "Secretary", _("Secretary")
    REVIEWER = "Reviewer", _("Reviewer")

    @classmethod
    def admins(cls) -> Sequence["ConferenceRole"]:
        return [cls.CHAIR, cls.SECRETARY]


class ConferenceRoleAssignment(TimeStampedModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        related_query_name="role_assignment",
        verbose_name=_("conference"),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conference_role_assignments",
        related_query_name="conference_role_assignment",
        verbose_name=_("user"),
    )
    role = models.CharField(_("role"), max_length=255, choices=ConferenceRole)

    class Meta:
        verbose_name = _("conference role assignment")
        verbose_name_plural = _("conference role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "user", "role"),
                name="unique_conference_role_assignment",
                violation_error_code="unique",
                violation_error_message=_(
                    "The conference role assignment already exists."
                ),
            ),
            models.CheckConstraint(
                name="conference_role_assignment_role_value",
                condition=Q(role__in=ConferenceRole.values),
            ),
        )
        indexes = (
            models.Index(fields=("user", "role")),
            models.Index(fields=("role",)),
        )

    def __str__(self) -> str:
        return f"[{self.conference}] {self.role}: {self.user}"


class TrackRole(models.TextChoices):
    CHAIR = "Chair", _("Chair")
    SECRETARY = "Secretary", _("Secretary")
    REVIEWER = "Reviewer", _("Reviewer")

    @classmethod
    def admins(cls) -> Sequence["TrackRole"]:
        return [cls.CHAIR, cls.SECRETARY]


class TrackRoleAssignment(TimeStampedModel):
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        related_query_name="role_assignment",
        verbose_name=_("track"),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="track_role_assignments",
        related_query_name="track_role_assignment",
        verbose_name=_("user"),
    )
    role = models.CharField(_("role"), max_length=255, choices=TrackRole)

    class Meta:
        verbose_name = _("track role assignment")
        verbose_name_plural = _("track role assignments")
        constraints = (
            models.UniqueConstraint(
                fields=("track", "user", "role"),
                name="unique_track_role_assignment",
                violation_error_code="unique",
                violation_error_message=_("The track role assignment already exists."),
            ),
            models.CheckConstraint(
                name="track_role_assignment_role_value",
                condition=Q(role__in=TrackRole.values),
            ),
        )
        indexes = (
            models.Index(fields=("user", "role")),
            models.Index(fields=("role",)),
        )

    def __str__(self) -> str:
        return f"[{self.track}] {self.role}: {self.user}"

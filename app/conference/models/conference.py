from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel
from app.utils.perm import Perm

from .keyword import Keyword


class Conference(TimeStampedModel):
    class Visibility(models.TextChoices):
        PUBLIC = "Public", _("Public")
        ADMIN_ONLY = "Admin-Only", _("Admin-Only")

    name = models.SlugField(
        _("name"),
        max_length=255,
        unique=True,
        help_text=_("Unique identifier for the conference (e.g., 'CBPK-2020')."),
    )
    display_name = models.CharField(
        _("display name"),
        max_length=255,
        help_text=_("Full title of the conference."),
    )
    active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this conference is active. "
            "Unselect this instead of deleting the conference."
        ),
    )
    keywords = models.ManyToManyField(
        Keyword,
        blank=True,
        verbose_name=_("keywords"),
        help_text=_(
            "Keywords applicable to this conference. "
            "This is only used to display options on the frontend "
            "and will not be enforced."
        ),
    )
    visibility = models.CharField(
        _("visibility"),
        max_length=128,
        choices=Visibility,
        default=Visibility.ADMIN_ONLY,
    )

    READ = Perm()
    WRITE = Perm()
    ADMIN = Perm()

    class Meta:
        verbose_name = _("conference")
        verbose_name_plural = _("conferences")
        indexes = (
            models.Index(fields=("active", "visibility", "create_time")),
            models.Index(fields=("create_time",)),
        )

    def __str__(self) -> str:
        return self.name


class Track(TimeStampedModel, ULIDModel):
    class Visibility(models.TextChoices):
        PUBLIC = "Public", _("Public")
        ADMIN_ONLY = "Admin-Only", _("Admin-Only")

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="tracks",
        related_query_name="track",
        verbose_name=_("conference"),
    )
    display_name = models.CharField(
        _("display name"),
        max_length=255,
        help_text=_("Name of the track."),
    )
    active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this track is active. "
            "Unselect this instead of deleting the track."
        ),
    )
    ordering = models.IntegerField(
        _("ordering"),
        default=0,
        help_text=_("Determines the display order of tracks."),
    )
    visibility = models.CharField(
        _("visibility"),
        max_length=128,
        choices=Visibility,
        default=Visibility.ADMIN_ONLY,
    )

    READ = Perm()
    WRITE = Perm()
    ADMIN = Perm()

    class Meta:
        verbose_name = _("track")
        verbose_name_plural = _("tracks")
        ordering = ("conference", "ordering", "display_name")
        indexes = (
            models.Index(
                fields=(
                    "conference",
                    "active",
                    "visibility",
                    "ordering",
                    "display_name",
                ),
            ),
            models.Index(fields=("conference", "ordering", "display_name")),
        )

    def __str__(self) -> str:
        return f"{self.conference} - {self.display_name}"

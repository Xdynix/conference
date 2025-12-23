from typing import Self

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from app.infra.models import Mutex
from app.utils.models import TimeStampedModel, ULIDModel

from .keyword import Keyword


class ConferenceQuerySet(models.QuerySet["Conference"]):
    def active(self) -> Self:
        return self.filter(active=True)


class Conference(TimeStampedModel):
    class Visibility(models.TextChoices):
        PUBLIC = "Public", _("Public")
        MEMBER_ONLY = "Member-Only", _("Member-Only")
        ADMIN_ONLY = "Admin-Only", _("Admin-Only")

    name = models.SlugField(
        _("name"),
        max_length=255,
        unique=True,
        help_text=_(
            "Unique identifier for the conference (e.g., 'CBPK-2020'). "
            "Used in URLs; treat as immutable after creation. "
            "Modifying this value may break existing links or API clients."
        ),
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

    objects = ConferenceQuerySet.as_manager()

    class Meta:
        verbose_name = _("conference")
        verbose_name_plural = _("conferences")
        indexes = (
            models.Index(fields=("active", "visibility", "create_time")),
            models.Index(fields=("create_time",)),
        )

    def __str__(self) -> str:
        return self.name


class CodePool(TimeStampedModel, ULIDModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="code_pools",
        related_query_name="code_pool",
        verbose_name=_("conference"),
    )
    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("Name of the pool (e.g., 'Main Tracks', 'Workshops')."),
    )
    prefix = models.SlugField(
        _("prefix"),
        max_length=32,
        help_text=_("Prefix for the paper codes (e.g., 'CBPK-2', 'CBPK-WS-')."),
    )
    next_sequence = models.PositiveIntegerField(
        _("next sequence"),
        default=1,
        help_text=_("Next sequence number to be allocated."),
    )

    class Meta:
        verbose_name = _("code pool")
        verbose_name_plural = _("code pools")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "prefix"),
                name="unique_pool_prefix",
                violation_error_code="unique",
                violation_error_message=_(
                    "A code pool with this prefix already exists for this conference."
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.conference} - {self.name} ({self.prefix})"

    def allocate_code(self) -> str:
        """Allocate the next sequence number and return the generated paper code.

        Thread-safe and process-safe; uses ``Mutex`` internally to serialize access.
        Callers do not need additional locking.

        Returns:
            Generated paper code (e.g., "CBPK-2001").
        """
        with Mutex.lock_in_transaction(str(self.pk), namespace="code_pool"):
            self.refresh_from_db(fields=["next_sequence"])
            sequence = self.next_sequence
            self.next_sequence = F("next_sequence") + 1
            self.save(update_fields=["next_sequence"])
            # `03d` padding is sufficient for most conferences (up to 999 papers per
            # pool). If wider padding is needed, add a `sequence_width` field.
            return f"{self.prefix}{sequence:03d}"


class TrackQuerySet(models.QuerySet["Track"]):
    def active(self) -> Self:
        return self.filter(
            conference__active=True,
            active=True,
        )


class Track(TimeStampedModel, ULIDModel):
    class Visibility(models.TextChoices):
        PUBLIC = "Public", _("Public")
        MEMBER_ONLY = "Member-Only", _("Member-Only")
        ADMIN_ONLY = "Admin-Only", _("Admin-Only")

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="tracks",
        related_query_name="track",
        verbose_name=_("conference"),
    )
    # There is no way to ensure the pool belongs to the same conference for now.
    # We have to ensure it on the application level.
    # TODO: Use a composite foreign key after Django adds support for it.
    code_pool = models.ForeignKey(
        CodePool,
        on_delete=models.PROTECT,
        limit_choices_to=Q(conference=F("conference")),
        null=True,
        blank=True,
        default=None,
        related_name="tracks",
        related_query_name="track",
        verbose_name=_("code pool"),
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
    submissions_enabled = models.BooleanField(
        _("submissions enabled"),
        default=False,
        help_text=_(
            "Whether this track is currently accepting paper submissions. "
            "When disabled, authors cannot submit new papers to this track. "
            "Administrators can still submit regardless of this setting."
        ),
    )

    objects = TrackQuerySet.as_manager()

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

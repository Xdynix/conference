from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel

from .keyword import Keyword


class Conference(TimeStampedModel):
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
    # TODO: Add visibility status (e.g. private/public).

    class Meta:
        verbose_name = _("conference")
        verbose_name_plural = _("conferences")
        # TODO: Add indexes.

    def __str__(self) -> str:
        return self.name


class Track(TimeStampedModel, ULIDModel):
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
    # TODO: Add visibility status (e.g. private/public).

    class Meta:
        verbose_name = _("track")
        verbose_name_plural = _("tracks")
        ordering = ("conference", "ordering", "display_name")
        # TODO: Add indexes.

    def __str__(self) -> str:
        return f"{self.conference} - {self.display_name}"

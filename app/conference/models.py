from django.db import models
from django.utils.translation import gettext_lazy as _

from app.core.models import AbstractRole, AbstractRoleAssignment, User
from app.utils.enums import Region
from app.utils.models import TimeStampedModel, ULIDModel


class Keyword(models.Model):
    text = models.CharField(_("text"), max_length=255, unique=True)

    def __str__(self) -> str:
        return self.text


class KeywordSet(models.Model):
    """Reusable collection of keywords for simplified conference creation.

    Keyword sets store commonly used keyword subsets that can be referenced in
    conference creation payloads. When a conference is created with
    `keyword_sets: [...]`, the keywords from those sets are copied to the conference's
    `keywords` field. This avoids having to specify individual keywords explicitly in
    every creation request.
    """

    name = models.CharField(_("name"), max_length=255, unique=True)
    keywords = models.ManyToManyField(
        Keyword,
        blank=True,
        verbose_name=_("keyword set"),
    )

    def __str__(self) -> str:
        return self.name


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
        # TODO: Add indexes.

    def __str__(self) -> str:
        return f"[{self.conference}] {self.role}: {self.user}"


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
        # TODO: Add indexes.

    def __str__(self) -> str:
        return f"[{self.track}] {self.role}: {self.user}"


class AbstractProfile(models.Model):
    given_name = models.CharField(
        _("given name"),
        max_length=150,
        blank=True,
        default="",
    )
    family_name = models.CharField(
        _("family name"),
        max_length=150,
        blank=True,
        default="",
    )
    affiliation = models.CharField(
        _("affiliation"),
        max_length=250,
        blank=True,
        default="",
        help_text=_(
            "Institution or organization with which the individual is associated "
            "(e.g., 'Department of Physics, University of Oxford')."
        ),
    )
    region_code = models.CharField(
        _("region code"),
        max_length=16,
        blank=True,
        default="",
        choices=(
            ("", _("(Empty)")),
            *((region.name, f"{region.name} - {_(region)}") for region in Region),
        ),
    )

    class Meta:
        abstract = True


class UserProfile(AbstractProfile):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("user"),
    )

    class Meta:
        verbose_name = _("user profile")
        verbose_name_plural = _("user profiles")

    def __str__(self) -> str:
        return f"{self.user}'s profile"

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.enums import Region
from app.utils.models import TimeStampedModel

from .conference import Conference
from .keyword import Keyword

User = get_user_model()


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
        choices=(
            ("", _("(Empty)")),
            *((region.name, f"{region.name} - {_(region)}") for region in Region),
        ),
        default="",
    )

    class Meta:
        abstract = True


class Profile(AbstractProfile):
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


class AbstractUserConferenceProfile(models.Model):
    desired_paper_count = models.PositiveIntegerField(
        _("desired paper count"),
        default=5,
        help_text=_("Number of papers the user wants to review."),
    )
    interested_keywords = models.ManyToManyField(
        Keyword,
        blank=True,
        related_name="+",
        verbose_name=_("interested keywords"),
        help_text=_("Keywords the user is interested in for paper assignment."),
    )

    class Meta:
        abstract = True


class UserConferenceProfile(AbstractUserConferenceProfile, TimeStampedModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conference_profiles",
        related_query_name="conference_profile",
        verbose_name=_("user"),
    )
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="user_profiles",
        related_query_name="user_profile",
        verbose_name=_("conference"),
    )

    class Meta:
        verbose_name = _("user conference profile")
        verbose_name_plural = _("user conference profiles")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "conference"),
                name="unique_user_conference_profile",
                violation_error_code="unique",
                violation_error_message=_(
                    "The user conference profile already exists."
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.user} @ {self.conference}"

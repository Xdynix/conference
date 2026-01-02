import secrets

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference
from .paper import Paper
from .profile import AbstractProfile

User = get_user_model()


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


def generate_reference_code() -> str:
    return f"{secrets.randbelow(100_000_000):08d}"


class RegistrationState(models.TextChoices):
    PENDING = "Pending", _("Pending")
    CONFIRMED = "Confirmed", _("Confirmed")
    CANCELLED = "Cancelled", _("Cancelled")


class RegistrationTitle(models.TextChoices):
    PROF = "Prof.", _("Prof.")
    DR = "Dr.", _("Dr.")
    MR = "Mr.", _("Mr.")
    MS = "Ms.", _("Ms.")


class Registration(AbstractProfile, TimeStampedModel, ULIDModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="registrations",
        related_query_name="registration",
        verbose_name=_("conference"),
    )
    reference_code = models.CharField(
        _("reference code"),
        max_length=32,
        default=generate_reference_code,
        help_text=_("Auto-generated code for matching offline payments."),
    )
    state = models.CharField(
        _("state"),
        max_length=32,
        choices=RegistrationState,
        default=RegistrationState.PENDING,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="registrations",
        related_query_name="registration",
        verbose_name=_("user"),
    )
    # There is no way to ensure the paper and type belongs to the same conference for
    # now. We have to ensure it on the application level.
    # TODO: Use a composite foreign key after Django adds support for it.
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        limit_choices_to=Q(conference=F("conference")),
        related_name="registrations",
        related_query_name="registration",
        verbose_name=_("paper"),
    )
    attendance_type = models.ForeignKey(
        AttendanceType,
        on_delete=models.PROTECT,
        limit_choices_to=Q(conference=F("conference")),
        related_name="registrations",
        related_query_name="registration",
        verbose_name=_("attendance type"),
    )
    receipt_title = models.CharField(
        _("receipt title"),
        max_length=250,
        blank=True,
        help_text=_("Name to appear on the receipt, such as an institution name."),
    )
    title = models.CharField(
        _("title"),
        max_length=64,
        choices=RegistrationTitle,
        blank=True,
    )
    email = models.EmailField(_("email address"), blank=True)
    phone = models.CharField(_("phone number"), max_length=128, blank=True)
    self_introduction = models.TextField(_("self introduction"), blank=True)

    class Meta:
        verbose_name = _("registration")
        verbose_name_plural = _("registrations")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "reference_code"),
                name="unique_reference_code",
                violation_error_code="unique",
                violation_error_message=_(
                    "A registration with this reference code already exists."
                ),
            ),
        )

    def __str__(self) -> str:
        name = f"{self.given_name} {self.family_name}".strip()
        return name or self.reference_code

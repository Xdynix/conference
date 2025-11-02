from enum import StrEnum

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference, Track
from .profile import AbstractProfile, AbstractUserConferenceProfile
from .role import ConferenceRole, TrackRole

User = get_user_model()


class Invitation(
    AbstractUserConferenceProfile,
    AbstractProfile,
    TimeStampedModel,
    ULIDModel,
):
    class Status(StrEnum):
        PENDING = "Pending"
        ACCEPTED = "Accepted"
        REJECTED = "Rejected"

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="invitations",
        related_query_name="invitation",
        verbose_name=_("conference"),
    )
    inviter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_invitations",
        related_query_name="sent_invitation",
        verbose_name=_("inviter"),
    )
    invitee_email = models.EmailField(_("invitee email"))
    invitee_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="received_invitations",
        related_query_name="received_invitation",
        verbose_name=_("invitee user"),
        help_text=_("Set when the invitation is accepted."),
    )
    accept_time = models.DateTimeField(
        _("accept time"),
        null=True,
        blank=True,
        default=None,
    )
    reject_time = models.DateTimeField(
        _("reject time"),
        null=True,
        blank=True,
        default=None,
    )
    conference_roles = models.ManyToManyField(
        ConferenceRole,
        blank=True,
        related_name="invitations",
        related_query_name="invitation",
        verbose_name=_("conference roles"),
    )
    last_email_sent_time = models.DateTimeField(
        _("last email sent"),
        null=True,
        blank=True,
        default=None,
    )
    email_send_count = models.PositiveIntegerField(_("email sent count"), default=0)

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        constraints = (
            models.UniqueConstraint(
                "conference",
                Lower("invitee_email"),
                condition=Q(accept_time__isnull=True),
                name="unique_pending_conference_invitation",
                violation_error_code="unique",
                violation_error_message=_(
                    "A pending invitation already exists for this conference and email."
                ),
            ),
        )
        indexes = (
            models.Index(fields=("conference", "accept_time", "reject_time")),
            models.Index(fields=("invitee_email",)),
        )

    def __str__(self) -> str:
        return f"{self.invitee_email} → {self.conference} ({self.status})"

    @property
    def status(self) -> Status:
        if self.accept_time is not None:
            return self.Status.ACCEPTED
        elif self.reject_time is not None:
            return self.Status.REJECTED
        return self.Status.PENDING


class InvitationTrackEntry(models.Model):
    invitation = models.ForeignKey(
        Invitation,
        on_delete=models.CASCADE,
        related_name="track_entries",
        related_query_name="track_entry",
        verbose_name=_("invitation"),
    )
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("track"),
    )
    roles = models.ManyToManyField(
        TrackRole,
        blank=True,
        related_name="+",
        verbose_name=_("roles"),
    )

    class Meta:
        verbose_name = _("track entry")
        verbose_name_plural = _("track entries")
        constraints = (
            models.UniqueConstraint(
                fields=("invitation", "track"),
                name="unique_invitation_track",
                violation_error_code="unique",
                violation_error_message=_(
                    "A track entry already exists for this invitation and track."
                ),
            ),
        )

    def __str__(self) -> str:
        roles = self.roles.order_by("name").values_list("name", flat=True)
        return f"{self.invitation}: {self.track} - {', '.join(roles)}"

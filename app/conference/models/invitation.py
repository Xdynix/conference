from enum import StrEnum

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from app.audit.types import Auditable, AuditResource, AuditResourceInfo
from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference, Track
from .profile import AbstractProfile, AbstractUserConferenceProfile
from .role import ConferenceRole, TrackRole

User = get_user_model()


class Invitation(
    Auditable,
    AbstractUserConferenceProfile,
    AbstractProfile,
    TimeStampedModel,
    ULIDModel,
):
    class State(StrEnum):
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
    # Use SET_NULL instead of CASCADE because invitations don't have direct ownership
    # from the inviter. They can be updated by conference admins or other authorized
    # users, not just the original inviter. Preserving the invitation record when users
    # are deleted maintains data integrity and allows continued management of the
    # invitation lifecycle.
    inviter = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
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
    last_email_send_time = models.DateTimeField(
        _("last email send time"),
        null=True,
        blank=True,
        default=None,
    )
    email_send_count = models.PositiveIntegerField(_("email sent count"), default=0)

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        constraints = (
            # Enforce uniqueness only for pending invitations. This allows the same
            # email to receive multiple invitations over time (e.g., accepting one
            # invitation, then later receiving another for additional roles), while
            # preventing duplicate pending invitations that would confuse recipients.
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
            models.CheckConstraint(
                # Defensive: normal flows set `invitee_user` together with
                # `accept_time`. If this constraint fires, data was corrupted or
                # manually edited.
                name="invitation_invitee_user_requires_accept_time",
                condition=Q(invitee_user__isnull=True) | Q(accept_time__isnull=False),
            ),
        )
        indexes = (
            models.Index(fields=("conference", "accept_time", "reject_time")),
            models.Index(fields=("invitee_email",)),
        )

    def __str__(self) -> str:
        return f"{self.invitee_email} → {self.conference} ({self.state})"

    @property
    def state(self) -> State:
        if self.accept_time is not None:
            return self.State.ACCEPTED
        elif self.reject_time is not None:
            return self.State.REJECTED
        return self.State.PENDING

    @property
    def mutable(self) -> bool:
        """Returns whether this invitation can be modified.

        Accepted invitations are immutable because roles have been assigned and profile
        data has been copied to UserConferenceProfile. Pending and rejected invitations
        remain mutable.
        """
        return self.state != self.State.ACCEPTED

    def audit_resource_info(self) -> AuditResourceInfo:
        return AuditResourceInfo(
            resource=AuditResource.INVITATION,
            resource_id=str(self.uid),
            resource_label=self.invitee_email,
        )


class InvitationConferenceRoleEntry(models.Model):
    invitation = models.ForeignKey(
        Invitation,
        on_delete=models.CASCADE,
        related_name="conference_role_entries",
        related_query_name="conference_role_entry",
        verbose_name=_("invitation"),
    )
    role = models.CharField(_("role"), max_length=255, choices=ConferenceRole)

    class Meta:
        verbose_name = _("invitation conference role entry")
        verbose_name_plural = _("invitation conference role entries")
        constraints = (
            models.UniqueConstraint(
                fields=("invitation", "role"),
                name="unique_invitation_conference_role",
                violation_error_code="unique",
                violation_error_message=_(
                    "A conference role entry already exists "
                    "for this invitation and role."
                ),
            ),
            models.CheckConstraint(
                name="invitation_conference_role_entry_role_value",
                condition=Q(role__in=ConferenceRole.values),
            ),
        )

    def __str__(self) -> str:
        return f"{self.invitation}: {self.role}"


class InvitationTrackRoleEntry(models.Model):
    invitation = models.ForeignKey(
        Invitation,
        on_delete=models.CASCADE,
        related_name="track_role_entries",
        related_query_name="track_role_entry",
        verbose_name=_("invitation"),
    )
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("track"),
    )
    role = models.CharField(_("role"), max_length=255, choices=TrackRole)

    class Meta:
        verbose_name = _("invitation track role entry")
        verbose_name_plural = _("invitation track role entries")
        constraints = (
            models.UniqueConstraint(
                fields=("invitation", "track", "role"),
                name="unique_invitation_track_role",
                violation_error_code="unique",
                violation_error_message=_(
                    "A track role entry already exists "
                    "for this invitation, track and role."
                ),
            ),
            models.CheckConstraint(
                name="invitation_track_role_entry_role_value",
                condition=Q(role__in=TrackRole.values),
            ),
        )

    def __str__(self) -> str:
        return f"{self.invitation}: {self.track.display_name} - {self.role}"

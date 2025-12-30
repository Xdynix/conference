from collections.abc import Sequence
from typing import Self

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel

from .paper import Paper

User = get_user_model()

MIN_SCORE = 1
MAX_SCORE = 5
SCORE_HELP_TEXT = _("Score from 1 (lowest) to 5 (highest).")


class ReviewState(models.TextChoices):
    PENDING = "Pending", _("Pending")
    DECLINED = "Declined", _("Declined")
    ACCEPTED = "Accepted", _("Accepted")
    SUBMITTED = "Submitted", _("Submitted")
    CANCELLED = "Cancelled", _("Cancelled")

    @classmethod
    def active(cls) -> Sequence["ReviewState"]:
        return [
            cls.PENDING,
            cls.ACCEPTED,
            cls.SUBMITTED,
        ]


class ReviewAssignmentLevel(models.TextChoices):
    CONFERENCE = "Conference", _("Conference")
    TRACK = "Track", _("Track")


class ReviewQuerySet(models.QuerySet["Review"]):
    def active(self) -> Self:
        return self.filter(
            paper__conference__active=True,
            paper__track__active=True,
            paper__delete_time__isnull=True,
        )


class Review(TimeStampedModel, ULIDModel):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="reviews",
        related_query_name="review",
        verbose_name=_("paper"),
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name="reviews",
        related_query_name="review",
        verbose_name=_("reviewer"),
        help_text=_(
            "The user assigned to review this paper. Null for offline reviews."
        ),
    )
    offline_reviewer_name = models.CharField(
        _("offline reviewer name"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "Display name for reviewers imported from external sources. "
            "Used when reviewer is null."
        ),
    )
    state = models.CharField(
        _("state"),
        max_length=32,
        choices=ReviewState,
        default=ReviewState.PENDING,
    )
    originality = models.PositiveSmallIntegerField(
        _("originality"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    significance = models.PositiveSmallIntegerField(
        _("significance"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    technical = models.PositiveSmallIntegerField(
        _("technical"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    reference = models.PositiveSmallIntegerField(
        _("reference"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    presentation = models.PositiveSmallIntegerField(
        _("presentation"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    match_topic = models.PositiveSmallIntegerField(
        _("match topic"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    recommendation = models.PositiveSmallIntegerField(
        _("recommendation"),
        null=True,
        blank=True,
        default=None,
        help_text=SCORE_HELP_TEXT,
    )
    contribution = models.TextField(_("contribution"), blank=True, default="")
    decision_reason = models.TextField(_("decision reason"), blank=True, default="")
    comments = models.TextField(
        _("comments"),
        blank=True,
        default="",
        help_text=_("Suggestions, questions, and feedback for the authors."),
    )
    confidential_remarks = models.TextField(
        _("confidential remarks"),
        blank=True,
        default="",
        help_text=_("Comments visible only to editors, not shared with authors."),
    )
    assigner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="assigned_reviews",
        related_query_name="assigned_review",
        verbose_name=_("assigner"),
        help_text=_("The admin who assigned this review."),
    )
    assignment_level = models.CharField(
        _("assignment level"),
        max_length=32,
        choices=ReviewAssignmentLevel,
        default=ReviewAssignmentLevel.CONFERENCE,
        help_text=_(
            "Whether assigned by conference or track admin. "
            "Track admins cannot cancel conference-level assignments."
        ),
    )
    submit_time = models.DateTimeField(
        _("submit time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("When the review was submitted."),
    )

    objects = ReviewQuerySet.as_manager()

    class Meta:
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        constraints = (
            models.UniqueConstraint(
                fields=("paper", "reviewer"),
                condition=(
                    Q(reviewer__isnull=False) & Q(state__in=ReviewState.active())
                ),
                name="unique_active_review",
                violation_error_code="unique",
                violation_error_message=_(
                    "An active review for this paper and reviewer already exists."
                ),
            ),
            models.UniqueConstraint(
                fields=("paper", "offline_reviewer_name"),
                condition=Q(reviewer__isnull=True) & ~Q(offline_reviewer_name=""),
                name="unique_offline_review",
                violation_error_code="unique",
                violation_error_message=_(
                    "An offline review for this paper and reviewer already exists."
                ),
            ),
            *(
                models.CheckConstraint(
                    condition=(
                        Q(**{f"{field}__isnull": True})
                        | Q(**{f"{field}__gte": MIN_SCORE, f"{field}__lte": MAX_SCORE})
                    ),
                    name=f"review_{field}_range",
                )
                for field in (
                    "originality",
                    "significance",
                    "technical",
                    "reference",
                    "presentation",
                    "match_topic",
                    "recommendation",
                )
            ),
        )

    def __str__(self) -> str:
        reviewer_display = self.reviewer or self.offline_reviewer_name or "(Unassigned)"
        return f"{self.paper} - {reviewer_display}"


class AdminComment(TimeStampedModel, ULIDModel):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="admin_comments",
        related_query_name="admin_comment",
        verbose_name=_("paper"),
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="admin_comments",
        related_query_name="admin_comment",
        verbose_name=_("author"),
        help_text=_("The admin who wrote this comment."),
    )
    content = models.TextField(
        _("content"),
        help_text=_("Feedback displayed anonymously to authors alongside reviews."),
    )

    class Meta:
        verbose_name = _("admin comment")
        verbose_name_plural = _("admin comments")

    def __str__(self) -> str:
        author_display = self.author or "(Unknown)"
        return f"{self.paper} - {author_display}"

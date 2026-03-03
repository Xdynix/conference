from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel

from .conference import Conference
from .paper import Paper

User = get_user_model()


class DuplicateReportState(models.TextChoices):
    SUCCESS = "Success", _("Success")
    FAILED = "Failed", _("Failed")


class DuplicateReport(TimeStampedModel):
    """Metadata for a single duplicate-detection scan run.

    Each scan produces one report. Successful reports contain match pairs; failed
    reports record the error reason (e.g. paper count exceeded the safety threshold).
    """

    state = models.CharField(
        _("state"),
        max_length=32,
        choices=DuplicateReportState,
        default=DuplicateReportState.SUCCESS,
    )
    error_message = models.TextField(
        _("error message"),
        blank=True,
        default="",
        help_text=_("Empty on success; describes the failure reason otherwise."),
    )

    class Meta:
        verbose_name = _("duplicate report")
        verbose_name_plural = _("duplicate reports")
        ordering = ("-create_time",)

    def __str__(self) -> str:
        return f"DuplicateReport {self.pk} ({self.state})"


class DuplicateMatchType(models.TextChoices):
    FILE_HASH = "File Hash", _("File Hash")
    TITLE_SIMILARITY = "Title Similarity", _("Title Similarity")


class DuplicateMatch(models.Model):
    """A single similarity edge between two papers within a report.

    Papers are stored in canonical order (``paper_a.pk < paper_b.pk``) to prevent
    mirrored duplicates. A pair can appear twice per report if it matches on both file
    hash and title similarity.
    """

    report = models.ForeignKey(
        DuplicateReport,
        on_delete=models.CASCADE,
        related_name="matches",
        related_query_name="match",
        verbose_name=_("report"),
    )
    paper_a = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("paper A"),
        help_text=_("The paper with the smaller primary key."),
    )
    paper_b = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("paper B"),
        help_text=_("The paper with the larger primary key."),
    )
    match_type = models.CharField(
        _("match type"),
        max_length=32,
        choices=DuplicateMatchType,
    )
    score = models.FloatField(
        _("score"),
        help_text=_("Similarity score from 0.0 (no match) to 1.0 (exact match)."),
    )

    class Meta:
        verbose_name = _("duplicate match")
        verbose_name_plural = _("duplicate matches")
        constraints = (
            models.CheckConstraint(
                name="paper_a_before_b",
                condition=Q(paper_a_id__lt=F("paper_b_id")),
            ),
            models.UniqueConstraint(
                fields=("report", "paper_a", "paper_b", "match_type"),
                name="unique_report_pair_type",
                violation_error_code="unique",
                violation_error_message=_("The match already exists."),
            ),
        )

    def __str__(self) -> str:
        return f"{self.paper_a_id}-{self.paper_b_id} ({self.match_type})"


class DuplicateAcknowledgment(TimeStampedModel):
    """Records that a conference admin has reviewed a duplicate pair.

    Acknowledgments are scoped to a conference: Conference A's acknowledgment does not
    affect Conference B's view of the same pair.
    """

    paper_a = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("paper A"),
        help_text=_("The paper with the smaller primary key."),
    )
    paper_b = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("paper B"),
        help_text=_("The paper with the larger primary key."),
    )
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="duplicate_acknowledgments",
        related_query_name="duplicate_acknowledgment",
        verbose_name=_("conference"),
        help_text=_("The conference whose admin acknowledged this pair."),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="+",
        verbose_name=_("user"),
    )
    note = models.TextField(
        _("note"),
        blank=True,
        default="",
        help_text=_("Admin's note explaining why the pair was acknowledged."),
    )

    class Meta:
        verbose_name = _("duplicate acknowledgment")
        verbose_name_plural = _("duplicate acknowledgments")
        constraints = (
            models.CheckConstraint(
                name="ack_paper_a_before_b",
                condition=Q(paper_a_id__lt=F("paper_b_id")),
            ),
            models.UniqueConstraint(
                fields=("conference", "paper_a", "paper_b"),
                name="unique_ack_per_conference",
                violation_error_code="unique",
                violation_error_message=_(
                    "This pair is already acknowledged for this conference."
                ),
            ),
        )

    def __str__(self) -> str:
        return f"[{self.conference}] {self.paper_a_id}-{self.paper_b_id}"

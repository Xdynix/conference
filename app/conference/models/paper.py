from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference, Track
from .keyword import Keyword
from .profile import AbstractProfile

User = get_user_model()


class PaperQuerySet(models.QuerySet["Paper"]):
    def active(self) -> Self:
        return self.filter(
            conference__active=True,
            track__active=True,
            delete_time__isnull=True,
        )


class Paper(TimeStampedModel, ULIDModel):
    class State(models.TextChoices):
        DRAFT = "Draft", _("Draft")
        SUBMITTED = "Submitted", _("Submitted")
        UNDER_REVIEW = "Under Review", _("Under Review")
        REJECTED = "Rejected", _("Rejected")
        ACCEPTED = "Accepted", _("Accepted")
        ACCEPTED_REVISION_NEEDED = (
            "Accepted (Revision Needed)",
            _("Accepted (Revision Needed)"),
        )

        @classmethod
        def decided(cls) -> Sequence["Paper.State"]:
            return [
                cls.REJECTED,
                cls.ACCEPTED,
                cls.ACCEPTED_REVISION_NEEDED,
            ]

    VisibleState = State | Literal["Withdrawn"]

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="papers",
        related_query_name="paper",
        verbose_name=_("conference"),
    )
    # There is no way to ensure the track belongs to the same conference for now.
    # We have to ensure it on the application level.
    # TODO: Use a composite foreign key after Django adds support for it.
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        limit_choices_to=Q(conference=F("conference")),
        related_name="papers",
        related_query_name="paper",
        verbose_name=_("track"),
    )
    code = models.SlugField(_("code"), max_length=128)
    state = models.CharField(
        _("state"),
        max_length=128,
        choices=State,
        default=State.DRAFT,
    )
    delete_time = models.DateTimeField(
        _("delete time"),
        null=True,
        blank=True,
        default=None,
        help_text=_(
            "Soft delete timestamp. "
            "Deleted papers are excluded from all normal queries and statistics. "
            "Distinct from withdrawal."
        ),
    )
    withdraw_time = models.DateTimeField(
        _("withdraw time"),
        null=True,
        blank=True,
        default=None,
        help_text=_(
            "Withdrawal timestamp. "
            "If set, the paper is considered withdrawn regardless of state. "
            "Withdrawn papers remain visible in statistics."
        ),
    )
    announce_time = models.DateTimeField(
        _("announce time"),
        null=True,
        blank=True,
        default=None,
        help_text=_(
            "When the decision was announced to the author. "
            "Authors only see their paper's decision state after this is set."
        ),
    )
    submit_time = models.DateTimeField(
        _("submit time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("When the paper was submitted for review."),
    )
    decide_time = models.DateTimeField(
        _("decide time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("When the review decision was made."),
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="papers",
        related_query_name="paper",
        verbose_name=_("owner"),
    )
    title = models.CharField(_("title"), max_length=512)
    abstract = models.TextField(_("abstract"), blank=True, default="")
    contribution = models.TextField(_("contribution"), blank=True, default="")
    keywords = models.ManyToManyField(
        Keyword,
        blank=True,
        related_name="+",
        verbose_name=_("keywords"),
    )

    objects = PaperQuerySet.as_manager()

    class Meta:
        verbose_name = _("paper")
        verbose_name_plural = _("papers")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "code"),
                name="unique_conference_code",
                violation_error_code="unique",
                violation_error_message=_("A paper with this code already exists."),
            ),
        )
        indexes = (
            models.Index(
                fields=("conference", "state"),
                name="conference_paper_state",
                condition=Q(delete_time__isnull=True),
            ),
        )

    def __str__(self) -> str:
        return f"[{self.track}] {self.code}"

    @property
    def visible_state(self) -> VisibleState:
        if self.withdraw_time is not None:
            return "Withdrawn"
        if self.announce_time is None and self.state in self.State.decided():
            return self.State.UNDER_REVIEW
        return self.State(self.state)


class PaperAuthor(AbstractProfile):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="authors",
        related_query_name="author",
        verbose_name=_("paper"),
    )
    ordering = models.PositiveSmallIntegerField(
        _("ordering"),
        default=0,
        help_text=_("Author ordering. Lower values appear first."),
    )
    email = models.EmailField(_("email address"), blank=True)
    phone = models.CharField(_("phone number"), max_length=128, blank=True)
    corresponding = models.BooleanField(
        _("corresponding"),
        default=False,
        help_text=_(
            "Whether this author is a corresponding author. "
            "Used for academic attribution in proceedings."
        ),
    )

    class Meta:
        verbose_name = _("paper author")
        verbose_name_plural = _("paper authors")
        ordering = ("ordering",)
        constraints = (
            models.UniqueConstraint(
                fields=("paper", "ordering"),
                name="unique_paper_author_ordering",
            ),
        )

    def __str__(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()


def paper_submission_path(instance: "PaperSubmission", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    filename = f"submission-rev{instance.revision}{ext}"
    paper = instance.paper
    return f"{paper.conference.name}/{paper.code}/{filename}"


class PaperSubmission(TimeStampedModel, ULIDModel):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="submissions",
        related_query_name="submission",
        verbose_name=_("paper"),
    )
    revision = models.PositiveIntegerField(_("revision"), default=0)
    file = models.FileField(_("file"), upload_to=paper_submission_path)
    uploader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="uploaded_submissions",
        related_query_name="uploaded_submission",
        verbose_name=_("uploader"),
    )

    class Meta:
        verbose_name = _("paper submission")
        verbose_name_plural = _("paper submissions")
        ordering = ("-revision",)
        constraints = (
            models.UniqueConstraint(
                fields=("paper", "revision"),
                name="unique_paper_submission_revision",
            ),
        )

    def __str__(self) -> str:
        return f"{self.paper} rev{self.revision}"

    @property
    def display_name(self) -> str:
        ext = Path(self.file.name).suffix.lower()
        return f"{self.paper.code}{ext}"


def paper_final_source_path(instance: "PaperFinal", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    filename = f"final-rev{instance.revision}-source{ext}"
    paper = instance.paper
    return f"{paper.conference.name}/{paper.code}/{filename}"


def paper_final_viewable_path(instance: "PaperFinal", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    filename = f"final-rev{instance.revision}-viewable{ext}"
    paper = instance.paper
    return f"{paper.conference.name}/{paper.code}/{filename}"


class PaperFinal(TimeStampedModel, ULIDModel):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="finals",
        related_query_name="final",
        verbose_name=_("paper"),
    )
    revision = models.PositiveIntegerField(_("revision"), default=0)
    source_file = models.FileField(_("source file"), upload_to=paper_final_source_path)
    viewable_file = models.FileField(
        _("viewable file"),
        upload_to=paper_final_viewable_path,
        blank=True,
    )
    uploader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="uploaded_finals",
        related_query_name="uploaded_final",
        verbose_name=_("uploader"),
    )

    class Meta:
        verbose_name = _("paper final")
        verbose_name_plural = _("paper finals")
        ordering = ("-revision",)
        constraints = (
            models.UniqueConstraint(
                fields=("paper", "revision"),
                name="unique_paper_final_revision",
            ),
        )

    def __str__(self) -> str:
        return f"{self.paper} final rev{self.revision}"

    @property
    def display_name(self) -> str:
        ext = Path(self.source_file.name).suffix.lower()
        return f"{self.paper.code}{ext}"

    @property
    def viewable_display_name(self) -> str | None:
        if not self.viewable_file:
            return None
        ext = Path(self.viewable_file.name).suffix.lower()
        return f"{self.paper.code}-viewable{ext}"


PAPER_DOCUMENT_PREFIX = "doc-"


def paper_document_path(instance: "PaperDocument", filename: str) -> str:
    paper = instance.paper
    return f"{paper.conference.name}/{paper.code}/{PAPER_DOCUMENT_PREFIX}{filename}"


class PaperDocument(TimeStampedModel, ULIDModel):
    class Type(models.TextChoices):
        ACCEPTANCE_LETTER = "acceptance_letter", _("Acceptance Letter")
        OTHER = "other", _("Other")

    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="documents",
        related_query_name="document",
        verbose_name=_("paper"),
    )
    type = models.CharField(_("type"), max_length=128, choices=Type)
    file = models.FileField(_("file"), upload_to=paper_document_path)

    class Meta:
        verbose_name = _("paper document")
        verbose_name_plural = _("paper documents")

    def __str__(self) -> str:
        return f"{self.paper} {self.get_type_display()}"

    @property
    def display_name(self) -> str:
        filename = Path(self.file.name).name
        if self.type == self.Type.ACCEPTANCE_LETTER:
            ext = Path(filename).suffix.lower()
            return f"{self.paper.code}-acceptance-letter{ext}"
        return filename.removeprefix(PAPER_DOCUMENT_PREFIX)

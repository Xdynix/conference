# TODO: if per-conference asset management is needed (e.g. different logos per
#  conference), consider adding a ConferenceAsset model with a FileField scoped to
#  conference. Currently, shared template assets live in DATA_DIR/assets/ and are loaded
#  at compile time via load_assets().

# TODO: consider a generic PaperDocument (and RegistrationDocument) model for
#  system-generated per-entity documents (e.g. visa invitation letters). Similar to
#  AcceptanceLetter (template + context -> rendered PDF, stored and queryable), but with
#  a slug-style `type` field instead of a dedicated model per document kind. The script
#  provides the template and context; the server renders and stores the PDF. This keeps
#  generation logic on the script side while making documents trackable and reusable as
#  email attachments via a new `paper_document` attachment ref type.

from pathlib import Path

from django.db import models
from django.utils.translation import gettext_lazy as _

from app.audit.types import Auditable, AuditResource, AuditResourceInfo
from app.utils.models import TimeStampedModel

from .conference import Conference
from .paper import Paper
from .registration import Registration


def acceptance_letter_path(instance: "AcceptanceLetter", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    paper = instance.paper
    return f"{paper.conference.name}/{paper.code}/acceptance-letter{ext}"


class AcceptanceLetter(TimeStampedModel):
    paper = models.OneToOneField(
        Paper,
        on_delete=models.CASCADE,
        related_name="acceptance_letter",
        verbose_name=_("paper"),
    )
    rendered_pdf = models.FileField(_("rendered PDF"), upload_to=acceptance_letter_path)
    template = models.TextField(_("template"))
    context = models.JSONField(_("context"))

    class Meta:
        verbose_name = _("acceptance letter")
        verbose_name_plural = _("acceptance letters")

    def __str__(self) -> str:
        return f"Acceptance letter for {self.paper}"


def receipt_path(instance: "Receipt", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    registration = instance.registration
    return f"{registration.conference.name}/receipts/{registration.uid}{ext}"


class Receipt(TimeStampedModel):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="receipt",
        verbose_name=_("registration"),
    )
    rendered_pdf = models.FileField(_("rendered PDF"), upload_to=receipt_path)
    template = models.TextField(_("template"))
    context = models.JSONField(_("context"))

    class Meta:
        verbose_name = _("receipt")
        verbose_name_plural = _("receipts")

    def __str__(self) -> str:
        return f"Receipt for {self.registration}"


def conference_file_path(instance: "ConferenceFile", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    return f"{instance.conference.name}/files/{instance.name}{ext}"


class ConferenceFile(Auditable, TimeStampedModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="files",
        related_query_name="file",
        verbose_name=_("conference"),
    )
    name = models.SlugField(
        _("name"),
        max_length=128,
        help_text=_(
            "Short slug-style identifier (e.g. 'payment-form', 'instructions')."
        ),
    )
    filename = models.CharField(
        _("filename"),
        max_length=255,
        help_text=_(
            "Sanitized original filename from the upload, used as the default "
            "attachment display name in emails."
        ),
    )
    file = models.FileField(_("file"), upload_to=conference_file_path)

    class Meta:
        verbose_name = _("conference file")
        verbose_name_plural = _("conference files")
        constraints = (
            models.UniqueConstraint(
                fields=["conference", "name"],
                name="unique_conference_file_name",
                violation_error_code="unique",
                violation_error_message=_("A file with this name already exists."),
            ),
        )

    def __str__(self) -> str:
        return f"{self.name} ({self.conference})"

    def audit_resource_info(self) -> AuditResourceInfo:
        return AuditResourceInfo(
            resource=AuditResource.CONFERENCE_FILE,
            resource_id=self.name,
            resource_label=str(self),
        )

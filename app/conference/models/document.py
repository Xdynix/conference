from pathlib import Path

from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel

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

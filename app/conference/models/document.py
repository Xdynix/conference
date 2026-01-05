from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel

from .paper import Paper
from .registration import Registration


class AcceptanceLetter(TimeStampedModel):
    paper = models.OneToOneField(
        Paper,
        on_delete=models.CASCADE,
        related_name="acceptance_letter",
        verbose_name=_("paper"),
    )
    rendered_html = models.TextField(_("rendered html"), blank=True, default="")

    class Meta:
        verbose_name = _("acceptance letter")
        verbose_name_plural = _("acceptance letters")

    def __str__(self) -> str:
        return f"Acceptance letter for {self.paper}"


class Receipt(TimeStampedModel):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="receipt",
        verbose_name=_("registration"),
    )
    rendered_html = models.TextField(_("rendered html"), blank=True, default="")

    class Meta:
        verbose_name = _("receipt")
        verbose_name_plural = _("receipts")

    def __str__(self) -> str:
        return f"Receipt for {self.registration}"

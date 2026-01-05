from django.db import models
from django.utils.translation import gettext_lazy as _

from app.utils.models import TimeStampedModel

from .conference import Conference, Track
from .paper import Paper


class IEEEeCopyrightConfig(models.Model):
    conference = models.OneToOneField(
        Conference,
        on_delete=models.CASCADE,
        related_name="ieee_ecopyright_config",
        verbose_name=_("conference"),
    )
    publication_title = models.CharField(_("publication title"), max_length=255)
    article_source = models.CharField(_("article source"), max_length=255)
    exempt_tracks = models.ManyToManyField(
        Track,
        blank=True,
        related_name="+",
        verbose_name=_("exempt tracks"),
    )

    class Meta:
        verbose_name = _("IEEE eCopyright config")
        verbose_name_plural = _("IEEE eCopyright configs")

    def __str__(self) -> str:
        return f"IEEE eCopyright config for {self.conference}"


class IEEEeCopyrightConsent(TimeStampedModel):
    paper = models.OneToOneField(
        Paper,
        on_delete=models.CASCADE,
        related_name="ieee_ecopyright_consent",
        verbose_name=_("paper"),
    )
    raw_response = models.JSONField(_("raw response"), blank=True, default=dict)

    class Meta:
        verbose_name = _("IEEE eCopyright consent")
        verbose_name_plural = _("IEEE eCopyright consents")

    def __str__(self) -> str:
        return f"IEEE eCopyright consent for {self.paper}"

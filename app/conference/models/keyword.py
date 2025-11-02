from django.db import models
from django.utils.translation import gettext_lazy as _


class Keyword(models.Model):
    text = models.CharField(_("text"), max_length=255, unique=True)

    class Meta:
        verbose_name = _("keyword")
        verbose_name_plural = _("keywords")
        ordering = ("text",)

    def __str__(self) -> str:
        return self.text


class KeywordSet(models.Model):
    """Reusable collection of keywords for simplified conference creation.

    Keyword sets store commonly used keyword subsets that can be referenced in
    conference creation payloads. When a conference is created with
    `keyword_sets: [...]`, the keywords from those sets are copied to the conference's
    `keywords` field. This avoids having to specify individual keywords explicitly in
    every creation request.
    """

    name = models.CharField(_("name"), max_length=255, unique=True)
    keywords = models.ManyToManyField(
        Keyword,
        blank=True,
        verbose_name=_("keyword set"),
    )

    class Meta:
        verbose_name = _("keyword set")
        verbose_name_plural = _("keyword sets")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

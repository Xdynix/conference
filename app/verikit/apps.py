"""User identity verification toolkit."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VerikitConfig(AppConfig):
    name = "app.verikit"
    verbose_name = _("Verification Toolkit")

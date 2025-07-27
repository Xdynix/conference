from django.db import models
from django.utils.translation import gettext_lazy as _
from ulid import ULID
from ulid_django.models import ULIDField


class ULIDModel(models.Model):
    """Model with a unique ULID field."""

    uid = ULIDField(_("UID"), unique=True, default=ULID, editable=False)

    class Meta:
        abstract = True

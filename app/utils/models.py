from django.db import models
from django.utils.translation import gettext_lazy as _
from ulid import ULID
from ulid_django.models import ULIDField


class ULIDModel(models.Model):
    """Model with a unique ULID field.

    Design decisions:
    - Retains Django's auto-increment primary key for optimal database performance
      (sequential writes, efficient joins, smaller index size).
    - Uses ULID as a separate public identifier to avoid exposing internal database
      keys in APIs and URLs, which could leak information about data volume and
      creation patterns.
    - ULID chosen over UUID v4: ULIDs are time-sortable and have better index
      performance due to their sequential prefix, while remaining globally unique.
      UUID v4 uses random bits, causing index fragmentation and unpredictable ordering.
    - ULID chosen over UUID v7: UUID v7 would also work (time-ordered like ULID), but
      it's not available in Python's standard library until Python 3.14. ULID provides
      similar benefits with existing library support and a more concise string
      representation (26 chars vs 36 chars).
    """

    uid = ULIDField(_("UID"), unique=True, default=ULID, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """Model with ``create_time`` and ``update_time`` fields defined."""

    create_time = models.DateTimeField(_("create time"), auto_now_add=True)
    update_time = models.DateTimeField(_("update time"), auto_now=True)

    class Meta:
        abstract = True

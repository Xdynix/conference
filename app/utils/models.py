from typing import assert_never, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, Manager, OuterRef, Q
from django.utils.translation import gettext_lazy as _
from ulid import ULID
from ulid_django.models import ULIDField

from app.utils.label_selector import LabelKey, LabelSelector, LabelValue, Operator


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


def validate_label_key(label_key: str) -> None:
    try:
        LabelKey(label_key)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def validate_label_value(label_value: str) -> None:
    try:
        LabelValue(label_value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


class LabelModel(models.Model):
    """Abstract model for Kubernetes-style labels."""

    key = models.CharField(
        _("key"),
        blank=False,
        max_length=LabelKey.MAX_LENGTH,
        validators=(validate_label_key,),
    )
    value = models.CharField(
        _("value"),
        blank=True,
        default="",
        max_length=LabelValue.MAX_LENGTH,
        validators=(validate_label_value,),
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.key}={self.value}"

    @classmethod
    def selector_q(
        cls,
        selector: LabelSelector,
        *,
        parent_field: str,
        outer_ref: str = "pk",
    ) -> Q:
        """Build a ``Q`` object for filtering parent objects by label selector.

        Args:
            selector: The label selector to match against.
            parent_field: The FK field name on this model pointing to the parent.
            outer_ref: The field path for OuterRef, typically "pk" for direct parent
                queries or a FK field name for nested queries.

        Returns:
            A ``Q`` object that can be used with the parent model's queryset.

        Example:
            Direct parent query (default ``outer_ref="pk"``)::

                # Find papers with env=prod
                q = PaperLabel.selector_q(selector, parent_field="paper")
                Paper.objects.filter(q)

            Nested query through a related model::

                # Find reviews where the reviewed paper has env=prod
                # Review has FK to Paper, so we reference Review.paper
                q = PaperLabel.selector_q(
                    selector,
                    parent_field="paper",
                    outer_ref="paper",
                )
                Review.objects.filter(q)
        """
        q = Q()

        objects = cast(Manager[LabelModel], cls.objects)  # type: ignore[attr-defined]

        for req in selector.requirements:
            base_filter = {parent_field: OuterRef(outer_ref), "key": req.key}

            match req.operator:
                case Operator.EQUALS | Operator.DOUBLE_EQUALS:
                    (value,) = req.values
                    subquery = objects.filter(**base_filter, value=value)
                    q &= Q(Exists(subquery))

                case Operator.IN:
                    subquery = objects.filter(**base_filter, value__in=req.values)
                    q &= Q(Exists(subquery))

                case Operator.NOT_EQUALS:
                    (value,) = req.values
                    subquery = objects.filter(**base_filter, value=value)
                    q &= ~Q(Exists(subquery))

                case Operator.NOT_IN:
                    subquery = objects.filter(**base_filter, value__in=req.values)
                    q &= ~Q(Exists(subquery))

                case Operator.EXISTS:
                    subquery = objects.filter(**base_filter)
                    q &= Q(Exists(subquery))

                case Operator.DOES_NOT_EXIST:
                    subquery = objects.filter(**base_filter)
                    q &= ~Q(Exists(subquery))

                case _ as unreachable:
                    assert_never(unreachable)

        return q

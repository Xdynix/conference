from decimal import Decimal
from typing import Self

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from app.audit.types import Auditable, AuditResource, AuditResourceInfo
from app.utils.models import TimeStampedModel, ULIDModel

from .conference import Conference
from .registration import Registration

# Currencies that do not use decimal places (non-decimal currencies).
NON_DECIMAL_CURRENCIES = frozenset({"JPY"})


def format_amount(amount: Decimal, currency: str) -> str:
    """Format an amount with currency code for display.

    Non-decimal currencies (e.g., JPY) are formatted without decimal places.
    All others are formatted with 2 decimal places. Thousands separators are used.

    >>> format_amount(Decimal("1234.56"), "USD")
    '1,234.56 USD'
    >>> format_amount(Decimal("1000.00"), "USD")
    '1,000.00 USD'
    >>> format_amount(Decimal("12345"), "JPY")
    '12,345 JPY'
    >>> format_amount(Decimal("12345.67"), "JPY")
    '12,345 JPY'
    >>> format_amount(Decimal("9999.99"), "CNY")
    '9,999.99 CNY'
    >>> format_amount(Decimal("1234567.89"), "EUR")
    '1,234,567.89 EUR'
    >>> format_amount(Decimal("0.00"), "USD")
    '0.00 USD'
    >>> format_amount(Decimal("0"), "JPY")
    '0 JPY'
    """
    if currency in NON_DECIMAL_CURRENCIES:
        return f"{int(amount):,} {currency}"
    return f"{amount:,.2f} {currency}"


class PaymentCurrency(models.TextChoices):
    CNY = "CNY", _("CNY - Renminbi")
    EUR = "EUR", _("EUR - Euro")
    HKD = "HKD", _("HKD - Hong Kong dollar")
    JPY = "JPY", _("JPY - Japanese yen")
    TWD = "TWD", _("TWD - New Taiwan dollar")
    USD = "USD", _("USD - United States dollar")


class PaymentType(models.TextChoices):
    PAYMENT = "Payment", _("Payment")
    REFUND = "Refund", _("Refund")


class PaymentMethod(models.TextChoices):
    OTHER = "Other", _("Other")
    CREDIT_CARD = "Credit Card", _("Credit Card")
    WIRE_TRANSFER = "Wire Transfer", _("Wire Transfer")


class PaymentQuerySet(models.QuerySet["Payment"]):
    def active(self) -> Self:
        return self.filter(
            conference__active=True,
            delete_time__isnull=True,
        )


class Payment(Auditable, TimeStampedModel, ULIDModel):
    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="payments",
        related_query_name="payment",
        verbose_name=_("conference"),
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=16, choices=PaymentCurrency)
    type = models.CharField(_("type"), max_length=64, choices=PaymentType)
    method = models.CharField(_("method"), max_length=64, choices=PaymentMethod)
    reference = models.CharField(
        _("reference"),
        max_length=255,
        blank=True,
        default="",
        help_text=_("External transaction ID from cashier or payment gateway."),
    )
    note = models.TextField(_("note"), blank=True, default="")
    delete_time = models.DateTimeField(
        _("delete time"),
        null=True,
        blank=True,
        default=None,
        help_text=_("Set to soft-delete this payment. Null means active."),
    )

    objects = PaymentQuerySet.as_manager()

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        constraints = (
            models.UniqueConstraint(
                fields=("conference", "reference"),
                condition=~Q(reference=""),
                name="unique_payment_reference",
                violation_error_code="unique",
                violation_error_message=_(
                    "A payment with this reference already exists."
                ),
            ),
            models.CheckConstraint(
                name="payment_amount_non_negative",
                condition=Q(amount__gte=0),
            ),
        )
        indexes = (models.Index(fields=("conference", "delete_time")),)

    def __str__(self) -> str:
        return (
            f"[{self.conference}] {self.get_type_display()} - "
            f"{self.amount} {self.currency}"
        )

    @property
    def formatted_amount(self) -> str:
        """Return the amount formatted with currency code for display."""
        return format_amount(self.amount, self.currency)

    def audit_resource_info(self) -> AuditResourceInfo:
        return AuditResourceInfo(
            resource=AuditResource.PAYMENT,
            resource_id=str(self.uid),
            resource_label=self.reference,
        )


class PaymentItem(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="items",
        related_query_name="item",
        verbose_name=_("payment"),
    )
    # There is no way to ensure the registration belongs to the same conference for now.
    # We have to ensure it on the application level.
    # TODO: Use a composite foreign key after Django adds support for it.
    registration = models.ForeignKey(
        Registration,
        on_delete=models.CASCADE,
        related_name="payment_items",
        related_query_name="payment_item",
        verbose_name=_("registration"),
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=12,
        decimal_places=2,
        help_text=_("Portion of the payment allocated to this registration."),
    )
    description = models.CharField(
        _("description"),
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        verbose_name = _("payment item")
        verbose_name_plural = _("payment items")
        constraints = (
            models.CheckConstraint(
                name="payment_item_amount_non_negative",
                condition=Q(amount__gte=0),
            ),
        )

    def __str__(self) -> str:
        return f"{self.amount} for {self.registration}"

    @property
    def formatted_amount(self) -> str:
        """Return the amount formatted with currency code for display."""
        return format_amount(self.amount, self.payment.currency)

"""Payment service for simple offline payment bookkeeping.

These methods are designed for admin recording of offline payments (cash, bank transfer,
etc.) with minimal validation. When integrating online payment processing, all methods
must be redesigned to handle payment gateway callbacks, idempotency, state machines, and
proper audit trails.
"""

from decimal import Decimal
from typing import NotRequired, TypedDict

from django.db import IntegrityError, transaction
from ulid import ULID

from app.conference.models import Payment, PaymentItem, Registration
from app.infra.models import Mutex


class PaymentItemData(TypedDict):
    registration: ULID
    amount: Decimal
    description: NotRequired[str]


class ReferenceConflictError(Exception):
    pass


class InvalidRegistrationError(Exception):
    def __init__(self, index: int, uid: ULID) -> None:
        super().__init__(f"Invalid registration at index {index}: {uid}.")
        self.index = index
        self.uid = uid


class PaymentService:
    @classmethod
    def create_payment(
        cls,
        payment: Payment,
        items: list[PaymentItemData] | None = None,
    ) -> Payment:
        """Create a new payment with optional items.

        Args:
            payment: An unsaved payment instance with all required fields set.
            items: Payment items to associate with this payment.

        Raises:
            ReferenceConflictError: If another payment in the same conference has the
                same reference.
            InvalidRegistrationError: If a registration UID is not found in the
                payment's conference.
        """
        with transaction.atomic():
            try:
                payment.save()
            except IntegrityError as exc:
                if payment.reference:  # pragma: no branch
                    raise ReferenceConflictError from exc
                raise  # pragma: no cover

            if items:
                cls._save_items(payment, items)

        return payment

    @classmethod
    def update_payment(
        cls,
        payment: Payment,
        update_fields: list[str],
        items: list[PaymentItemData] | None = None,
    ) -> Payment:
        """Update an existing payment and optionally replace items.

        Args:
            payment: An existing payment instance with modified fields.
            update_fields: Fields to update. These fields plus ``update_time`` are
                saved.
            items: Payment items to replace existing items. If ``None``, items are left
                unchanged. If empty list, all items are removed.

        Raises:
            ReferenceConflictError: If another payment in the same conference has the
                same reference.
            InvalidRegistrationError: If a registration UID is not found in the
                payment's conference.
        """
        with Mutex.lock_in_transaction(str(payment.pk), namespace="payment"):
            if update_fields:
                try:
                    payment.save(update_fields=[*update_fields, "update_time"])
                except IntegrityError as exc:
                    if payment.reference:  # pragma: no branch
                        raise ReferenceConflictError from exc
                    raise  # pragma: no cover

            if items is not None:
                payment.items.all().delete()
                if items:
                    cls._save_items(payment, items)

        return payment

    @classmethod
    def _save_items(cls, payment: Payment, items: list[PaymentItemData]) -> None:
        """Validate registrations and create payment items."""
        registration_uids = [item["registration"] for item in items]
        registrations = {
            r.uid: r
            for r in Registration.objects.filter(
                conference_id=payment.conference_id,
                uid__in=registration_uids,
            )
        }

        for i, item in enumerate(items):
            if item["registration"] not in registrations:
                raise InvalidRegistrationError(index=i, uid=item["registration"])

        PaymentItem.objects.bulk_create(
            [
                PaymentItem(
                    payment=payment,
                    registration=registrations[item["registration"]],
                    amount=item["amount"],
                    description=item.get("description", ""),
                )
                for item in items
            ]
        )

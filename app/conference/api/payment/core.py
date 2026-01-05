from typing import Literal

from django.db.models import QuerySet
from django.utils.translation import gettext as _
from ninja import Field, Router
from pydantic import AwareDatetime
from ulid import ULID

from app.conference.models import Payment, Registration, RegistrationState
from app.conference.types import PaperCode
from app.conference.types import Payment as PaymentSchema
from app.conference.types import PaymentItem as PaymentItemSchema
from app.conference.types import Profile as ProfileSchema
from app.core.types import EmailStr

router = Router(tags=["Payment"], exclude_none=True)


class PaymentItemRegistrationResponse(ProfileSchema):
    uid: ULID
    reference_code: str
    state: RegistrationState
    paper: PaperCode | None
    attendance_type: str
    receipt_title: str
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))

    @staticmethod
    def resolve_paper(registration: Registration) -> str | None:
        return registration.paper.code if registration.paper else None

    @staticmethod
    def resolve_attendance_type(registration: Registration) -> str:
        return registration.attendance_type.display_name


class PaymentItemResponse(PaymentItemSchema):
    registration: PaymentItemRegistrationResponse


class PaymentResponse(PaymentSchema):
    uid: ULID
    create_time: AwareDatetime
    update_time: AwareDatetime
    items: list[PaymentItemResponse]

    @staticmethod
    def resolve_conference(payment: Payment) -> str:
        return payment.conference.name


def with_payment_prefetch(queryset: QuerySet[Payment]) -> QuerySet[Payment]:
    """Prefetch related data for payment queries."""
    return queryset.select_related("conference").prefetch_related(
        "items__registration__paper",
        "items__registration__attendance_type",
    )


async def prefetch_payment(payment: Payment) -> Payment:
    """Refetch a payment with all related data prefetched for serialization."""
    qs = with_payment_prefetch(Payment.objects.all())
    return await qs.aget(pk=payment.pk)

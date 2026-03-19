from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Status
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Payment
from app.conference.services import PaymentService
from app.conference.services.payment import (
    InvalidRegistrationError,
    PaymentItemData,
    ReferenceConflictError,
)
from app.conference.types import Payment as BasePaymentSchema
from app.conference.types import PaymentItem as BasePaymentItemSchema
from app.conference.types import PaymentNote, PaymentReference
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaymentResponse, prefetch_payment, router


class PaymentItemSchema(BasePaymentItemSchema):
    registration: ULID


class CreatePaymentRequest(BasePaymentSchema):
    reference: PaymentReference = ""
    note: PaymentNote = ""
    items: list[PaymentItemSchema] = Field(default_factory=list, max_length=100)


@router.post(
    "/conferences/{slug:conference_name}/payments",
    response={
        HTTPStatus.CREATED: PaymentResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create Payment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def create_payment(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreatePaymentRequest,
) -> Status[Payment]:
    """Creates a new payment record for offline payment bookkeeping."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    payment = Payment(
        conference=conference,
        amount=payload.amount,
        currency=payload.currency,
        type=payload.type,
        method=payload.method,
        reference=payload.reference,
        note=payload.note,
    )

    items_data: list[PaymentItemData] = [
        PaymentItemData(
            registration=item.registration,
            amount=item.amount,
            description=item.description,
        )
        for item in payload.items
    ]

    try:
        await sync_to_async(PaymentService.create_payment)(payment, items=items_data)
    except ReferenceConflictError as exc:
        raise HttpError(
            HTTPStatus.CONFLICT,
            _("A payment with this reference already exists."),
        ) from exc
    except InvalidRegistrationError as exc:
        raise make_validation_error(
            path=["items", exc.index, "registration"],
            message=_("Registration not found in this conference."),
        ) from exc

    await audit(
        request=request,
        action=AuditAction.PAYMENT_CREATE,
        resource=payment,
        scope=conference.name,
        payload=payload,
    )

    return Status(HTTPStatus.CREATED, await prefetch_payment(payment))

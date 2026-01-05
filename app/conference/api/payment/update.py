from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, PatchDict
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Payment
from app.conference.services import PaymentService
from app.conference.services.payment import (
    InvalidRegistrationError,
    ReferenceConflictError,
)
from app.conference.types import Payment as BasePaymentSchema
from app.conference.types import PaymentItem as BasePaymentItemSchema
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaymentResponse, prefetch_payment, router


class PaymentItemSchema(BasePaymentItemSchema):
    registration: ULID


class PaymentSchema(BasePaymentSchema):
    items: list[PaymentItemSchema] = Field(default_factory=list, max_length=100)


@router.patch(
    "/conferences/{slug:conference_name}/payments/{ulid:payment_uid}",
    response={
        HTTPStatus.OK: PaymentResponse,
        HTTPStatus.CONFLICT: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update Payment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def update_payment(
    request: AuthedHttpRequest,
    conference_name: str,
    payment_uid: ULID,
    payload: PatchDict[PaymentSchema],
) -> Payment:
    """Updates a payment record.

    All fields are optional; omitted fields retain their existing values. When items
    are provided, they replace all existing items.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    payment = await aget_object_or_404(
        conference.payments.active(),
        uid=payment_uid,
    )

    if not payload:
        return await prefetch_payment(payment)

    try:
        items_data = payload.pop("items", None)

        for field, value in payload.items():
            setattr(payment, field, value)

        await sync_to_async(PaymentService.update_payment)(
            payment,
            update_fields=list(payload),
            items=items_data,
        )
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

    user = await request.auser()
    logger.info(
        "Payment updated.",
        payment_uid=str(payment.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return await prefetch_payment(payment)

from django.shortcuts import aget_object_or_404
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Payment
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import PaymentResponse, prefetch_payment, router


@router.get(
    "/conferences/{slug:conference_name}/payments/{ulid:payment_uid}",
    response=PaymentResponse,
    summary="Get Payment",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def get_payment(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    payment_uid: ULID,
) -> Payment:
    """Returns a specific payment with its associated items."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    payment = await aget_object_or_404(
        conference.payments.active(),
        uid=payment_uid,
    )
    return await prefetch_payment(payment)

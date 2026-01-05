from http import HTTPStatus

from django.shortcuts import aget_object_or_404
from django.utils import timezone
from loguru import logger
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


@router.delete(
    "/conferences/{slug:conference_name}/payments/{ulid:payment_uid}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Payment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def delete_payment(
    request: AuthedHttpRequest,
    conference_name: str,
    payment_uid: ULID,
) -> tuple[int, None]:
    """Soft-deletes a payment record."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    payment = await aget_object_or_404(
        conference.payments.active(),
        uid=payment_uid,
    )

    payment.delete_time = timezone.now()
    await payment.asave(update_fields=["delete_time", "update_time"])

    user = await request.auser()
    logger.info(
        "Payment deleted.",
        payment_uid=str(payment.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return HTTPStatus.NO_CONTENT, None

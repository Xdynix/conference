from typing import Annotated

from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja import FilterLookup, FilterSchema, Query
from ninja.pagination import paginate
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Payment
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import cursor_pagination

from .core import PaymentResponse, router, with_payment_prefetch


class ListPaymentsFilters(FilterSchema):
    registration: Annotated[ULID | None, FilterLookup("item__registration__uid")] = None


@router.get(
    "/conferences/{slug:conference_name}/payments",
    response=list[PaymentResponse],
    summary="List Payments",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
@paginate(cursor_pagination(cursor_field="uid", cursor_type=ULID))
async def list_payments(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    filters: Query[ListPaymentsFilters],
) -> QuerySet[Payment]:
    """Returns all payments for this conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    payments = conference.payments.active()
    payments = filters.filter(payments).distinct()

    return with_payment_prefetch(payments)

from urllib.parse import urljoin

from django.db.models import CharField, Exists, OuterRef, QuerySet, Value
from django.http import HttpRequest
from django.urls import reverse
from ninja import Router
from pydantic import HttpUrl

from app.conference.models import Receipt, Registration
from app.conference.types import ConferenceUser
from app.conference.types import Registration as RegistrationSchema

router = Router(tags=["Registration"], exclude_none=True)


class BaseRegistrationResponse(RegistrationSchema):
    @staticmethod
    def resolve_conference(registration: Registration) -> str:
        return registration.conference.name


class UserRegistrationResponse(BaseRegistrationResponse):
    pass


class RegistrationResponse(BaseRegistrationResponse):
    user: ConferenceUser
    receipt_url: HttpUrl | None

    @staticmethod
    def resolve_receipt_url(registration: Registration) -> HttpUrl | None:
        if not registration.has_receipt:  # type: ignore[attr-defined]
            return None
        base_url: str = registration.api_base_url  # type: ignore[attr-defined]
        path = reverse(
            "api-1.0.0:get-receipt-ex",
            args=[registration.uid, "receipt.pdf"],
        )
        return HttpUrl(urljoin(base_url, path))


def with_registration_prefetch(
    queryset: QuerySet[Registration],
    request: HttpRequest,
) -> QuerySet[Registration]:
    """Prefetch related data for registration queries."""
    return queryset.select_related(
        "conference",
        "user__profile",
        "paper",
        "attendance_type",
    ).annotate(
        has_receipt=Exists(Receipt.objects.filter(registration=OuterRef("pk"))),
        api_base_url=Value(
            request.build_absolute_uri("/"),
            output_field=CharField(),
        ),
    )


async def prefetch_registration(
    registration: Registration,
    request: HttpRequest,
) -> Registration:
    """Refetch a registration with all related data prefetched for serialization."""
    qs = with_registration_prefetch(Registration.objects.all(), request)
    return await qs.aget(pk=registration.pk)

from django.db.models import QuerySet
from ninja import Router

from app.conference.models import Registration
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


def with_registration_prefetch(
    queryset: QuerySet[Registration],
) -> QuerySet[Registration]:
    """Prefetch related data for registration queries."""
    return queryset.select_related(
        "conference",
        "user__profile",
        "paper",
        "attendance_type",
    )


async def prefetch_registration(registration: Registration) -> Registration:
    """Refetch a registration with all related data prefetched for serialization."""
    qs = with_registration_prefetch(Registration.objects.all())
    return await qs.aget(pk=registration.pk)

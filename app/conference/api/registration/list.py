from typing import Annotated

from django.db.models import QuerySet
from django.shortcuts import aget_object_or_404
from ninja import FilterLookup, FilterSchema, Query
from ninja.pagination import paginate
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Registration
from app.conference.services import ConferenceService
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.pagination import cursor_pagination

from .core import (
    RegistrationResponse,
    UserRegistrationResponse,
    router,
    with_registration_prefetch,
)


@router.get(
    "/conferences/{slug:conference_name}/my-registrations",
    response=list[UserRegistrationResponse],
    summary="List My Registrations",
    auth=is_authenticated,
)
@paginate(cursor_pagination(cursor_field="uid", cursor_type=ULID))
async def list_my_registrations(
    request: AuthedHttpRequest,
    conference_name: str,
) -> QuerySet[Registration]:
    """Returns all registrations created by the current user for this conference."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    # Base queryset mirrors has_registrations annotation in conference/core.py.
    registrations = conference.registrations.filter(user=user)

    return with_registration_prefetch(registrations, request)


class ListRegistrationsFilters(FilterSchema):
    search: Annotated[
        str | None,
        FilterLookup(
            [
                "reference_code__icontains",
                "paper__code__icontains",
                "given_name__icontains",
                "family_name__icontains",
                "email__icontains",
            ],
        ),
    ] = None


@router.get(
    "/conferences/{slug:conference_name}/registrations",
    response=list[RegistrationResponse],
    summary="List Registrations",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
@paginate(cursor_pagination(cursor_field="uid", cursor_type=ULID))
async def list_registrations(
    request: AuthedHttpRequest,
    conference_name: str,
    filters: Query[ListRegistrationsFilters],
) -> QuerySet[Registration]:
    """Returns all registrations for this conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    registrations = conference.registrations.all()
    registrations = filters.filter(registrations)

    return with_registration_prefetch(registrations, request)

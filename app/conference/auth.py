import warnings

from django.shortcuts import aget_object_or_404

from app.conference.models import Conference, ConferenceRole, ConferenceRoleAssignment
from app.core.auth import SessionAuth, authorization
from app.core.models import User
from app.core.types import HttpRequest


def has_any_conference_roles(
    *roles: ConferenceRole,
    name_param: str = "conference_name",
) -> SessionAuth:
    @authorization
    async def _has_any_conference_roles(request: HttpRequest, user: User) -> bool:
        if user.is_superuser:
            return True

        resolver_match = getattr(request, "resolver_match", None)
        if resolver_match is None:  # pragma: no cover
            warnings.warn(
                (
                    "SessionAuth cannot resolve conference parameter; "
                    "resolver data missing."
                ),
                UserWarning,
                stacklevel=1,
            )
            return False

        conference_name = resolver_match.kwargs.get(name_param)
        if conference_name is None:  # pragma: no cover
            warnings.warn(
                f"SessionAuth conference parameter {name_param!r} missing.",
                UserWarning,
                stacklevel=1,
            )
            return False

        conference = await aget_object_or_404(
            Conference.objects.filter(active=True),
            name=conference_name,
        )
        return await ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=user,
            role__in=roles,
        ).aexists()

    return _has_any_conference_roles

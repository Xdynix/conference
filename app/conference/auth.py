import warnings

from django.shortcuts import aget_object_or_404
from django.urls import ResolverMatch

from app.conference.models import (
    ConferenceRole,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService
from app.core.auth import SessionAuth, authorization
from app.core.models import User
from app.core.types import HttpRequest


def _get_resolver_match(request: HttpRequest) -> ResolverMatch | None:
    """Get the resolver match from the request, warning if unavailable."""
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:  # pragma: no cover
        warnings.warn(
            "SessionAuth cannot resolve URL parameters; resolver data missing.",
            UserWarning,
            stacklevel=2,
        )
    return resolver_match


def has_any_conference_roles(
    *roles: ConferenceRole,
    name_param: str = "conference_name",
) -> SessionAuth:
    """Create a Django Ninja auth requiring specified conference roles.

    Checks if the authenticated user has at least one of the given conference roles for
    the conference specified in the URL path. Superusers always pass.

    The conference must be visible to the user (respects visibility rules).

    Example::

        @router.get(
            "/conferences/{conference_name}/data",
            auth=has_any_conference_roles(
                ConferenceRole.CHAIR,
                ConferenceRole.SECRETARY,
            )
        )
    """

    @authorization
    async def _has_any_conference_roles(request: HttpRequest, user: User) -> bool:
        if user.is_superuser:
            return True

        resolver_match = _get_resolver_match(request)
        if resolver_match is None:  # pragma: no cover
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
            await ConferenceService.visible_conferences(user),
            name=conference_name,
        )
        return await conference.role_assignments.filter(
            user=user,
            role__in=roles,
        ).aexists()

    return _has_any_conference_roles


def has_any_track_roles(
    *roles: TrackRole,
    conference_name_param: str = "conference_name",
    track_id_param: str = "track_id",
) -> SessionAuth:
    """Create a Django Ninja auth requiring specified track roles.

    Checks if the authenticated user has at least one of the given track roles for the
    specific track specified in the URL path. Superusers always pass.

    Both the conference and the track must be visible to the user (respects visibility
    rules).

    Example:
        @router.get(
            "/conferences/{conference_name}/tracks/{track_id}/data",
            auth=has_any_track_roles(TrackRole.CHAIR, TrackRole.SECRETARY)
        )
    """

    @authorization
    async def _has_any_track_roles(request: HttpRequest, user: User) -> bool:
        if user.is_superuser:
            return True

        resolver_match = _get_resolver_match(request)
        if resolver_match is None:  # pragma: no cover
            return False

        conference_name = resolver_match.kwargs.get(conference_name_param)
        if conference_name is None:  # pragma: no cover
            warnings.warn(
                f"SessionAuth conference parameter {conference_name_param!r} missing.",
                UserWarning,
                stacklevel=1,
            )
            return False

        track_id = resolver_match.kwargs.get(track_id_param)
        if track_id is None:  # pragma: no cover
            warnings.warn(
                f"SessionAuth track parameter {track_id_param!r} missing.",
                UserWarning,
                stacklevel=1,
            )
            return False

        conference = await aget_object_or_404(
            await ConferenceService.visible_conferences(user),
            name=conference_name,
        )
        tracks = await ConferenceService.visible_tracks(user)
        track = await aget_object_or_404(
            tracks.filter(conference=conference),
            uid=track_id,
        )
        return await track.role_assignments.filter(
            user=user,
            role__in=roles,
        ).aexists()

    return _has_any_track_roles


def has_any_conference_or_track_roles(
    *roles: ConferenceRole | TrackRole,
    conference_name_param: str = "conference_name",
) -> SessionAuth:
    """Create a Django Ninja auth requiring conference or track roles.

    Checks if the authenticated user has at least one of the given roles, which can be
    either conference-level roles or track-level roles in any visible track within the
    conference. Superusers always pass.

    For track roles, only considers tracks that are visible to the user (respects track
    visibility rules). Useful for endpoints that need to permit both conference and
    track administrators.

    Example:
        @router.get(
            "/conferences/{conference_name}/invitations",
            auth=has_any_conference_or_track_roles(
                ConferenceRole.CHAIR,
                ConferenceRole.SECRETARY,
                TrackRole.CHAIR,
                TrackRole.SECRETARY,
            )
        )
    """

    @authorization
    async def _has_any_conference_or_track_roles(
        request: HttpRequest, user: User
    ) -> bool:
        if user.is_superuser:
            return True

        resolver_match = _get_resolver_match(request)
        if resolver_match is None:  # pragma: no cover
            return False

        conference_name = resolver_match.kwargs.get(conference_name_param)
        if conference_name is None:  # pragma: no cover
            warnings.warn(
                f"SessionAuth conference parameter {conference_name_param!r} missing.",
                UserWarning,
                stacklevel=1,
            )
            return False

        conference = await aget_object_or_404(
            await ConferenceService.visible_conferences(user),
            name=conference_name,
        )

        # Split roles by type.
        conference_roles = [r for r in roles if isinstance(r, ConferenceRole)]
        track_roles = [r for r in roles if isinstance(r, TrackRole)]

        # Check conference roles.
        if (
            conference_roles
            and await conference.role_assignments.filter(
                user=user,
                role__in=conference_roles,
            ).aexists()
        ):
            return True

        # Check track roles (only visible tracks in this conference).
        if track_roles:
            tracks = await ConferenceService.visible_tracks(user)
            return await TrackRoleAssignment.objects.filter(
                track__in=tracks.filter(conference=conference),
                user=user,
                role__in=track_roles,
            ).aexists()

        return False

    return _has_any_conference_or_track_roles

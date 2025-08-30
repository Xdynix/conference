__all__ = ("ConferencePermissionService",)

from collections.abc import Container

from django.contrib.auth.models import AnonymousUser

from app.conference.models import Conference, Track
from app.core.models import Permission, User


class ConferencePermissionService:
    @classmethod
    async def get_conference_permissions(
        cls,
        user: User | AnonymousUser,
        conference: Conference,
    ) -> Container[str]:
        """Return the conference-scoped permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(
                conferencerole__assignment__user=user,
                conferencerole__assignment__conference=conference,
            )

        return await Permission.to_keys(permissions)

    @classmethod
    async def get_track_permissions(
        cls,
        user: User | AnonymousUser,
        track: Track,
    ) -> Container[str]:
        """Return the track-scoped permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(
                trackrole__assignment__user=user,
                trackrole__assignment__track=track,
            )

        return await Permission.to_keys(permissions)

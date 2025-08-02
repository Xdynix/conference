from collections.abc import Container

from django.contrib.auth.models import AnonymousUser

from app.core.models import Permission, User


class PermissionService:
    @classmethod
    async def get_permissions(cls, user: User | AnonymousUser) -> Container[str]:
        """Return the globally granted permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(role__assignment__user=user)

        return {
            key async for key in permissions.values_list("key", flat=True).distinct()
        }

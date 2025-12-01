from typing import Any

from django.db.models import Prefetch, QuerySet
from ninja import Router

from app.conference.models import Conference, Profile
from app.conference.services import RoleAssignmentService
from app.conference.types import RoleAssignment as RoleAssignmentSchema
from app.core.models import User

router = Router(tags=["Role Assignment"], exclude_none=True)


class RoleAssignmentResponse(RoleAssignmentSchema):
    @staticmethod
    def resolve_profile(user: User) -> Profile | None:
        return getattr(user, "profile", None)

    @staticmethod
    def resolve_conference_roles(user: User) -> list[str]:
        return [
            assignment.role
            for assignment in user.visible_conference_roles  # type: ignore[attr-defined]
        ]

    @staticmethod
    def resolve_track_roles(user: User) -> list[dict[str, Any]]:
        return [
            {"uid": assignment.track.uid, "role": assignment.role}
            for assignment in user.visible_track_roles  # type: ignore[attr-defined]
        ]


async def with_role_assignment_prefetch(
    queryset: QuerySet[User],
    conference: Conference,
    requesting_user: User,
) -> QuerySet[User]:
    """Apply prefetch_related for role assignment serialization to a queryset."""
    visible_conference_assignments = (
        await RoleAssignmentService.visible_conference_role_assignments(
            conference,
            requesting_user,
        )
    )
    visible_track_assignments = (
        await RoleAssignmentService.visible_track_role_assignments(
            conference,
            requesting_user,
        )
    )

    return queryset.select_related("profile").prefetch_related(
        Prefetch(
            "conference_role_assignments",
            queryset=visible_conference_assignments.order_by("role"),
            to_attr="visible_conference_roles",
        ),
        Prefetch(
            "track_role_assignments",
            queryset=visible_track_assignments.select_related("track").order_by(
                "track__ordering", "track__display_name", "role"
            ),
            to_attr="visible_track_roles",
        ),
    )

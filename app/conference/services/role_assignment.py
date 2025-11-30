from collections.abc import Collection

from django.db.models import Exists, OuterRef, Q, QuerySet

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, User


class RoleAssignmentService:
    @classmethod
    async def visible_users_with_roles(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[User]:
        """Return users who have ≥1 visible role in the conference.

        A user is visible if they have at least one visible conference role or at least
        one visible track role on an active track.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all users with any
          conference or track role (on active tracks).
        - Conference admins (chairs and secretaries) see all users with any conference
          or track role (on active tracks).
        - Track admins see only users who have ≥1 role on active tracks they administer.
        - Other users see no users.
        """
        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()

        if is_global_privileged or is_conference_admin:
            conference_assignments = ConferenceRoleAssignment.objects.filter(
                conference=conference,
                user=OuterRef("pk"),
            )
            track_assignments = TrackRoleAssignment.objects.filter(
                track__conference=conference,
                track__active=True,
                user=OuterRef("pk"),
            )

            return (
                User.objects.active()
                .annotate(
                    has_conference_assignments=Exists(conference_assignments),
                    has_track_assignments=Exists(track_assignments),
                )
                .filter(
                    Q(has_conference_assignments=True) | Q(has_track_assignments=True)
                )
            )

        administered_track_ids = [
            track_id
            async for track_id in (
                conference.tracks.active()
                .filter(
                    role_assignment__user=user,
                    role_assignment__role__in=TrackRole.admins(),
                )
                .distinct()
                .values_list("pk", flat=True)
            )
        ]

        if not administered_track_ids:
            return User.objects.active().none()

        track_assignments = TrackRoleAssignment.objects.filter(
            track__active=True,
            track_id__in=administered_track_ids,
            user=OuterRef("pk"),
        )

        return (
            User.objects.active()
            .annotate(has_track_assignments=Exists(track_assignments))
            .filter(has_track_assignments=True)
        )

    @classmethod
    async def visible_conference_role_assignments(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[ConferenceRoleAssignment]:
        """Return conference role assignments visible to the user.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all assignments.
        - Conference admins (chairs and secretaries) see all assignments.
        - Track admins see no conference role assignments (outside their scope).
        - Other users see no assignments.
        """
        assignments = conference.role_assignments.all()

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return assignments

        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()
        if is_conference_admin:
            return assignments

        return assignments.none()

    @classmethod
    async def visible_track_role_assignments(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[TrackRoleAssignment]:
        """Return track role assignments visible to the user.

        Only assignments on active tracks are included. Inactive tracks are treated as
        non-existent.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all assignments on
          active tracks.
        - Conference admins (chairs and secretaries) see all assignments on active
          tracks.
        - Track admins see only assignments on active tracks they administer.
        - Other users see no assignments.
        """
        assignments = TrackRoleAssignment.objects.filter(
            track__conference=conference,
            track__active=True,
        )

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return assignments

        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()
        if is_conference_admin:
            return assignments

        administered_track_ids = [
            track_id
            async for track_id in (
                conference.tracks.active()
                .filter(
                    role_assignment__user=user,
                    role_assignment__role__in=TrackRole.admins(),
                )
                .distinct()
                .values_list("pk", flat=True)
            )
        ]

        if not administered_track_ids:
            return assignments.none()

        return assignments.filter(track_id__in=administered_track_ids)

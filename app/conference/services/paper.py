from collections.abc import Collection

from django.db.models import QuerySet

from app.conference.models import Conference, ConferenceRole, Paper, TrackRole
from app.core.models import GlobalRole, User


class PaperService:
    @classmethod
    async def visible_papers(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Paper]:
        """Return papers for the conference visible to the user.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all papers.
        - Conference admins (chairs and secretaries) see all papers.
        - Track admins see only papers in tracks they administer.
        - Other users see no papers.
        """
        papers = conference.papers.active()

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return papers

        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()
        if is_conference_admin:
            return papers

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
            return papers.none()

        return papers.filter(track_id__in=administered_track_ids)

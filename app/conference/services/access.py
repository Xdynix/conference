from collections.abc import Collection
from dataclasses import dataclass

from app.conference.models import Conference, ConferenceRole, Track, TrackRole
from app.core.models import GlobalRole, User


@dataclass(frozen=True, slots=True)
class ConferenceAccessContext:
    conference: Conference
    user: User
    global_privileged: bool
    conference_admin: bool
    has_full_conference_scope: bool
    administered_track_ids: frozenset[int]

    def can_admin_track(self, track: Track) -> bool:
        if track.conference_id != self.conference.pk:
            return False

        if self.has_full_conference_scope:
            return True

        return track.pk in self.administered_track_ids


class ConferenceAccessService:
    @classmethod
    async def context(
        cls,
        *,
        conference: Conference,
        user: User,
        global_roles: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> ConferenceAccessContext:
        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(role__in=global_roles).aexists()
        )
        if is_global_privileged:
            return ConferenceAccessContext(
                conference=conference,
                user=user,
                global_privileged=True,
                conference_admin=False,
                has_full_conference_scope=True,
                administered_track_ids=frozenset(),
            )

        is_conference_admin = await conference.role_assignments.filter(
            user=user,
            role__in=ConferenceRole.admins(),
        ).aexists()
        if is_conference_admin:
            return ConferenceAccessContext(
                conference=conference,
                user=user,
                global_privileged=False,
                conference_admin=True,
                has_full_conference_scope=True,
                administered_track_ids=frozenset(),
            )

        administered_track_ids = frozenset(
            [
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
        )
        return ConferenceAccessContext(
            conference=conference,
            user=user,
            global_privileged=False,
            conference_admin=False,
            has_full_conference_scope=False,
            administered_track_ids=administered_track_ids,
        )

    @classmethod
    async def can_admin_track(
        cls,
        *,
        conference: Conference,
        track: Track,
        user: User,
        global_roles: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> bool:
        ctx = await cls.context(
            conference=conference,
            user=user,
            global_roles=global_roles,
        )
        return ctx.can_admin_track(track)

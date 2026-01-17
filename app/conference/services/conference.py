from collections import defaultdict
from collections.abc import Collection, Mapping
from datetime import date
from typing import Literal, TypedDict

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils.translation import gettext as _

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceVisibility,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
)
from app.conference.services import ConferenceAccessService
from app.core.models import GlobalRole, User
from app.infra.models import Mutex


class ConferenceNameConflict(Exception):
    pass


class InsufficientRolePermission(Exception):
    pass


class TrackData(TypedDict):
    display_name: str
    visibility: TrackVisibility


class ConferenceService:
    @classmethod
    @transaction.atomic
    def create_conference(
        cls,
        *,
        name: str,
        display_name: str,
        visibility: ConferenceVisibility,
        registration_enabled: bool,
        keywords: Collection[Keyword],
        keyword_sets: Collection[KeywordSet],
        tracks: Collection[TrackData],
        start_date: date | None = None,
        end_date: date | None = None,
        location: str = "",
        paper_submission_instructions: str = "",
        paper_final_instructions: str = "",
    ) -> Conference:
        """Creates a new conference with associated keywords and tracks.

        Returns:
            The newly created conference instance.

        Raises:
            ConferenceNameConflict: If a conference with that name already exists.
        """
        try:
            conference = Conference.objects.create(
                name=name,
                display_name=display_name,
                visibility=visibility,
                registration_enabled=registration_enabled,
                start_date=start_date,
                end_date=end_date,
                location=location,
                paper_submission_instructions=paper_submission_instructions,
                paper_final_instructions=paper_final_instructions,
            )
        except IntegrityError as exc:
            raise ConferenceNameConflict from exc

        assigned_keywords: set[Keyword] = set(keywords)
        for keyword_set in keyword_sets:
            assigned_keywords.update(keyword_set.keywords.all())
        if assigned_keywords:
            conference.keywords.set(assigned_keywords)

        track_objects = [
            Track(
                conference=conference,
                display_name=track["display_name"],
                ordering=idx,
                visibility=track["visibility"],
            )
            for idx, track in enumerate(tracks)
        ]
        if track_objects:
            Track.objects.bulk_create(track_objects)

        return conference

    @classmethod
    def update_conference(
        cls,
        *,
        name: str,
        display_name: str | None = None,
        visibility: ConferenceVisibility | None = None,
        registration_enabled: bool | None = None,
        keywords: Collection[Keyword] | None = None,
        keyword_sets: Collection[KeywordSet] | None = None,
        start_date: date | Literal[""] | None = None,
        end_date: date | Literal[""] | None = None,
        location: str | None = None,
        paper_submission_instructions: str | None = None,
        paper_final_instructions: str | None = None,
    ) -> Conference:
        """Updates a conference's attributes.

        For date fields (``start_date``, ``end_date``), pass an empty string to clear
        the value (set to ``None``). Omit the parameter to leave the existing value
        unchanged.

        Returns:
            The updated conference instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        with Mutex.lock_in_transaction(name, namespace="conference"):
            conference = Conference.objects.active().get(name=name)

            update_fields: list[str] = []

            if display_name is not None:
                conference.display_name = display_name
                update_fields.append("display_name")

            if visibility is not None:
                conference.visibility = visibility
                update_fields.append("visibility")

            if registration_enabled is not None:
                conference.registration_enabled = registration_enabled
                update_fields.append("registration_enabled")

            if start_date is not None:
                conference.start_date = None if start_date == "" else start_date
                update_fields.append("start_date")

            if end_date is not None:
                conference.end_date = None if end_date == "" else end_date
                update_fields.append("end_date")

            if location is not None:
                conference.location = location
                update_fields.append("location")

            if paper_submission_instructions is not None:
                conference.paper_submission_instructions = paper_submission_instructions
                update_fields.append("paper_submission_instructions")

            if paper_final_instructions is not None:
                conference.paper_final_instructions = paper_final_instructions
                update_fields.append("paper_final_instructions")

            keywords_provided = keywords is not None
            keyword_sets_provided = keyword_sets is not None
            keywords_updated = keywords_provided or keyword_sets_provided
            if keywords_updated:
                assigned_keywords: set[Keyword] = set()
                assigned_keywords.update(keywords or [])
                for keyword_set in keyword_sets or []:
                    assigned_keywords.update(keyword_set.keywords.all())
                conference.keywords.set(assigned_keywords)

            if update_fields or keywords_updated:
                conference.save(update_fields=[*update_fields, "update_time"])

            return conference

    @classmethod
    def deactivate_conference(cls, *, name: str) -> Conference:
        """Deactivates a conference.

        Returns:
            The deactivated conference instance.

        Raises:
            Conference.DoesNotExist: If the conference is not found.
        """
        with Mutex.lock_in_transaction(name, namespace="conference"):
            conference = Conference.objects.active().get(name=name)
            conference.active = False
            conference.save(update_fields=["active", "update_time"])
            return conference

    @classmethod
    async def visible_conferences(
        cls,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Conference]:
        """Return the queryset of active conferences visible to ``user``.

        The queryset includes:

        - all public conferences;
        - all conferences when the user is a superuser or holds any ``global_readable``
          role;
        - conferences where the user is a conference admin (regardless of visibility);
        - conferences where the user is an admin on at least one active track
          (regardless of visibility); and
        - member-only conferences where the user has any conference or track role.
        """
        conferences = Conference.objects.active()

        if not user.is_authenticated:
            return conferences.filter(visibility=ConferenceVisibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return conferences

        is_public = Q(visibility=ConferenceVisibility.PUBLIC)
        is_conference_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            track__active=True,
            track__role_assignment__user=user,
            track__role_assignment__role__in=TrackRole.admins(),
        )
        is_member_only = Q(visibility=ConferenceVisibility.MEMBER_ONLY)
        has_any_conference_role = Q(role_assignment__user=user)
        has_any_track_role = Q(track__active=True, track__role_assignment__user=user)
        return conferences.filter(
            is_public
            | is_conference_admin
            | is_track_admin
            | (is_member_only & (has_any_conference_role | has_any_track_role))
        ).distinct()

    @classmethod
    async def visible_tracks(
        cls,
        user: User | AnonymousUser,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Track]:
        """Return the queryset of active tracks visible to ``user``.

        The queryset includes:

        - all public tracks;
        - all tracks when the user is a superuser or holds any ``global_readable`` role;
        - tracks whose parent conference the user administers (regardless of
          visibility);
        - tracks where the user has a track-admin role (regardless of visibility); and
        - member-only tracks where the user has any track role.
        """
        tracks = Track.objects.active()

        if not user.is_authenticated:
            return tracks.filter(visibility=TrackVisibility.PUBLIC)

        is_global_privileged = user.is_superuser or (
            await user.global_role_assignments.filter(
                role__in=global_readable
            ).aexists()
        )
        if is_global_privileged:
            return tracks

        is_public = Q(visibility=TrackVisibility.PUBLIC)
        is_conference_admin = Q(
            conference__role_assignment__user=user,
            conference__role_assignment__role__in=ConferenceRole.admins(),
        )
        is_track_admin = Q(
            role_assignment__user=user,
            role_assignment__role__in=TrackRole.admins(),
        )
        is_member_only = Q(visibility=TrackVisibility.MEMBER_ONLY)
        has_any_track_role = Q(role_assignment__user=user)
        return tracks.filter(
            is_public
            | is_conference_admin
            | is_track_admin
            | (is_member_only & has_any_track_role)
        ).distinct()

    @classmethod
    def validate_can_assign_roles(
        cls,
        user: User,
        conference: Conference,
        conference_roles: Collection[str] = (),
        track_roles: Mapping[Track, Collection[str]] | None = None,
    ) -> None:
        """Validate that the user can assign the specified roles.

        Permission rules:

        - Superusers and global admins can assign any roles.
        - Conference chairs can assign any roles.
        - Conference secretaries can assign REVIEWER or MEMBER roles (conference or
          track).
        - Track chairs can assign any track roles for their administered tracks.
        - Track secretaries can assign only REVIEWER or MEMBER track roles for their
          tracks.

        Raises:
            ValueError: If tracks do not belong to the conference.
            InsufficientRolePermission: If user lacks permission to assign the roles.
        """
        requested_conference_roles = set(conference_roles)
        requested_track_roles = {
            track: set(roles) for track, roles in (track_roles or {}).items()
        }

        invalid_tracks = [
            track
            for track in requested_track_roles
            if track.conference_id != conference.pk or not track.active
        ]
        if invalid_tracks:
            raise ValueError(
                _(
                    "The following tracks do not belong to this conference: {tracks}."
                ).format(
                    tracks=", ".join(track.display_name for track in invalid_tracks)
                )
            )

        if (
            user.is_superuser
            or user.global_role_assignments.filter(role=GlobalRole.ADMIN).exists()
        ):
            return

        user_conference_roles = set(
            conference.role_assignments.filter(
                user=user,
                role__in=ConferenceRole.admins(),
            ).values_list("role", flat=True)
        )
        is_conference_chair = ConferenceRole.CHAIR in user_conference_roles
        is_conference_secretary = ConferenceRole.SECRETARY in user_conference_roles

        if requested_conference_roles:
            if not (is_conference_chair or is_conference_secretary):
                raise InsufficientRolePermission(
                    _(
                        "You must be a conference chair or secretary to assign "
                        "conference roles."
                    )
                )

            if is_conference_secretary and not is_conference_chair:
                restricted_conference_roles = sorted(
                    role
                    for role in requested_conference_roles
                    if role not in (ConferenceRole.REVIEWER, ConferenceRole.MEMBER)
                )
                if restricted_conference_roles:
                    raise InsufficientRolePermission(
                        _(
                            "Conference secretaries can only assign the REVIEWER and "
                            "MEMBER roles, not: {roles}."
                        ).format(roles=", ".join(restricted_conference_roles))
                    )

        if not requested_track_roles:
            return

        if is_conference_chair:
            return

        specified_track_ids = [track.id for track in requested_track_roles]
        user_track_admin_roles: defaultdict[int, set[str]] = defaultdict(set)
        admin_assignments = TrackRoleAssignment.objects.filter(
            track_id__in=specified_track_ids,
            user=user,
            role__in=TrackRole.admins(),
        ).values_list("track_id", "role")
        for track_id, role in admin_assignments:
            user_track_admin_roles[track_id].add(role)

        for track, roles in requested_track_roles.items():
            track_admin_roles = user_track_admin_roles.get(track.pk, set())

            if TrackRole.CHAIR in track_admin_roles:
                continue

            if is_conference_secretary:
                restricted_track_roles = sorted(
                    role
                    for role in roles
                    if role not in (TrackRole.REVIEWER, TrackRole.MEMBER)
                )
                if restricted_track_roles:
                    raise InsufficientRolePermission(
                        _(
                            "Conference secretaries can only assign the REVIEWER and "
                            'MEMBER roles for track "{track}", not: {roles}.'
                        ).format(
                            track=track.display_name,
                            roles=", ".join(restricted_track_roles),
                        )
                    )
                continue

            if not track_admin_roles:
                raise InsufficientRolePermission(
                    _(
                        "You must be a track chair or secretary for track "
                        '"{track}" to assign roles to it.'
                    ).format(track=track.display_name)
                )

            restricted_track_roles = sorted(
                role
                for role in roles
                if role not in (TrackRole.REVIEWER, TrackRole.MEMBER)
            )
            if restricted_track_roles:
                raise InsufficientRolePermission(
                    _(
                        "Track secretaries can only assign the REVIEWER and MEMBER "
                        'roles for track "{track}", not: {roles}.'
                    ).format(
                        track=track.display_name,
                        roles=", ".join(restricted_track_roles),
                    )
                )

    @classmethod
    async def visible_attendance_types(
        cls,
        user: User,
        conference: Conference,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[AttendanceType]:
        """Return the queryset of attendance types visible to the user.

        Visibility rules:

        - Global admins and conference admins see all attendance types.
        - If registration is disabled, regular users see an empty list.
        - Otherwise, regular users see non-admin-only types.
        """
        attendance_types = AttendanceType.objects.filter(conference=conference)

        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=user,
            global_roles=global_readable,
        )
        if ctx.has_full_conference_scope:
            return attendance_types

        if not conference.registration_enabled:
            return attendance_types.none()

        return attendance_types.filter(admin_only=False)

import pytest

from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
)
from app.conference.services import ConferenceService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import a_update_object


@pytest.mark.django_db(transaction=True)
class TestConferenceServiceVisibleAttendanceTypes:
    @pytest.fixture
    def public_type(self, conference: Conference) -> AttendanceType:
        return AttendanceType.objects.create(
            conference=conference,
            display_name="Public",
            admin_only=False,
        )

    @pytest.fixture
    def admin_only_type(self, conference: Conference) -> AttendanceType:
        return AttendanceType.objects.create(
            conference=conference,
            display_name="Admin Only",
            admin_only=True,
        )

    async def test_superuser_sees_all_types(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
        admin_only_type: AttendanceType,
    ) -> None:
        await a_update_object(user, is_superuser=True)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert set(types) == {public_type, admin_only_type}

    async def test_global_admin_sees_all_types(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
        admin_only_type: AttendanceType,
    ) -> None:
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.ADMIN)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert set(types) == {public_type, admin_only_type}

    async def test_global_read_all_sees_all_types(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
        admin_only_type: AttendanceType,
    ) -> None:
        await GlobalRoleAssignment.objects.acreate(user=user, role=GlobalRole.READ_ALL)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert set(types) == {public_type, admin_only_type}

    @pytest.mark.parametrize("role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_types(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
        admin_only_type: AttendanceType,
        role: ConferenceRole,
    ) -> None:
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=role,
        )

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert set(types) == {public_type, admin_only_type}

    async def test_regular_user_registration_disabled_sees_empty(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,  # noqa: ARG002
    ) -> None:
        await a_update_object(conference, registration_enabled=False)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert types == []

    async def test_regular_user_registration_enabled_sees_non_admin_only(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
        admin_only_type: AttendanceType,  # noqa: ARG002
    ) -> None:
        await a_update_object(conference, registration_enabled=True)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert types == [public_type]

    async def test_admin_bypasses_registration_toggle(
        self,
        user: User,
        conference: Conference,
        public_type: AttendanceType,
    ) -> None:
        await a_update_object(conference, registration_enabled=False)
        await a_update_object(user, is_superuser=True)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert types == [public_type]

    @pytest.mark.parametrize(
        "role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    async def test_non_admin_conference_role_does_not_grant_full_visibility(
        self,
        user: User,
        conference: Conference,
        admin_only_type: AttendanceType,  # noqa: ARG002
        role: ConferenceRole,
    ) -> None:
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=role,
        )
        await a_update_object(conference, registration_enabled=True)

        qs = await ConferenceService.visible_attendance_types(user, conference)
        types = [t async for t in qs]

        assert types == []

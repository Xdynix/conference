import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService
from app.conference.services.conference import InsufficientRolePermission
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import update_object


@pytest.mark.django_db
class TestConferenceServiceValidateCanAssignRoles:
    def test_superuser_can_assign_any_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        update_object(user, is_superuser=True)

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[*ConferenceRole],
            track_roles={track_a: [*TrackRole]},
        )

    def test_global_admin_can_assign_any_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        GlobalRoleAssignment.objects.create(
            user=user,
            role=GlobalRole.ADMIN,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[*ConferenceRole],
            track_roles={track_a: [*TrackRole]},
        )

    def test_conference_chair_can_assign_any_conference_roles(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[*ConferenceRole],
        )

    def test_conference_chair_can_assign_any_track_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        track_b: Track,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            track_roles={
                track_a: [*TrackRole],
                track_b: [TrackRole.SECRETARY],
            },
        )

    @pytest.mark.parametrize(
        "assignable_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    def test_conference_secretary_can_assign_non_admin_conference_role(
        self,
        user: User,
        conference: Conference,
        assignable_role: ConferenceRole,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[assignable_role],
        )

    @pytest.mark.parametrize("restricted_role", ConferenceRole.admins())
    def test_conference_secretary_cannot_assign_admin_conference_role(
        self,
        user: User,
        conference: Conference,
        restricted_role: ConferenceRole,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match=(
                "Conference secretaries can only assign the REVIEWER and MEMBER roles"
            ),
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[restricted_role],
            )

    @pytest.mark.parametrize(
        "assignable_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_conference_secretary_can_assign_non_admin_track_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        assignable_role: TrackRole,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            track_roles={track_a: [assignable_role]},
        )

    @pytest.mark.parametrize("restricted_role", TrackRole.admins())
    def test_conference_secretary_cannot_assign_admin_track_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        restricted_role: TrackRole,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match=(
                "Conference secretaries can only assign the REVIEWER and MEMBER roles"
            ),
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                track_roles={track_a: [restricted_role]},
            )

    def test_conference_secretary_can_assign_both_conference_and_track_non_admin_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[ConferenceRole.REVIEWER, ConferenceRole.MEMBER],
            track_roles={track_a: [TrackRole.REVIEWER, TrackRole.MEMBER]},
        )

    def test_track_chair_can_assign_any_track_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            track_roles={
                track_a: [*TrackRole],
            },
        )

    @pytest.mark.parametrize("conference_role", ConferenceRole)
    def test_track_chair_cannot_assign_conference_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        conference_role: ConferenceRole,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.CHAIR,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match=(
                "You must be a conference chair or secretary to assign conference roles"
            ),
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[conference_role],
            )

    @pytest.mark.parametrize(
        "assignable_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    def test_track_secretary_can_assign_non_admin_track_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        assignable_role: TrackRole,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.SECRETARY,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            track_roles={track_a: [assignable_role]},
        )

    @pytest.mark.parametrize("conference_role", ConferenceRole)
    def test_track_secretary_cannot_assign_conference_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        conference_role: ConferenceRole,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.SECRETARY,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match=(
                "You must be a conference chair or secretary to assign conference roles"
            ),
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[conference_role],
            )

    @pytest.mark.parametrize("restricted_role", TrackRole.admins())
    def test_track_secretary_cannot_assign_admin_track_role(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        restricted_role: TrackRole,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.SECRETARY,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match="Track secretaries can only assign the REVIEWER and MEMBER roles",
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                track_roles={track_a: [restricted_role]},
            )

    def test_user_without_conference_role_cannot_assign_conference_roles(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        with pytest.raises(
            InsufficientRolePermission,
            match=(
                "You must be a conference chair or secretary to assign conference roles"
            ),
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[ConferenceRole.REVIEWER],
            )

    def test_user_without_track_role_cannot_assign_track_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        with pytest.raises(
            InsufficientRolePermission,
            match="You must be a track chair or secretary for track",
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                track_roles={track_a: [TrackRole.REVIEWER]},
            )

    @pytest.mark.parametrize("track_admin_role", TrackRole.admins())
    def test_track_admin_must_have_role_for_all_specified_tracks(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        track_b: Track,
        track_admin_role: TrackRole,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=track_admin_role,
        )

        with pytest.raises(
            InsufficientRolePermission,
            match="You must be a track chair or secretary for track",
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[],
                track_roles={
                    track_a: [TrackRole.REVIEWER],
                    track_b: [TrackRole.REVIEWER],
                },
            )

    def test_user_with_both_chair_and_secretary_can_assign_any_roles(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.SECRETARY],
            track_roles={},
        )

    def test_track_chair_can_assign_mixed_roles_to_multiple_tracks(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        track_b: Track,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.CHAIR,
        )
        TrackRoleAssignment.objects.create(
            track=track_b,
            user=user,
            role=TrackRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[],
            track_roles={
                track_a: [TrackRole.CHAIR, TrackRole.REVIEWER],
                track_b: [TrackRole.SECRETARY],
            },
        )

    def test_empty_roles_is_valid(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
        )

    def test_conference_chair_can_assign_both_conference_and_track_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

    def test_cannot_assign_track_from_different_conference(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )

        with pytest.raises(
            ValueError,
            match="The following tracks do not belong to this conference",
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[],
                track_roles={other_track: [TrackRole.REVIEWER]},
            )

    def test_inactive_track_rejected_as_not_belonging_to_conference(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        update_object(track_a, active=False)

        with pytest.raises(
            ValueError,
            match="The following tracks do not belong to this conference",
        ):
            ConferenceService.validate_can_assign_roles(
                user=user,
                conference=conference,
                conference_roles=[],
                track_roles={track_a: [TrackRole.REVIEWER]},
            )

    @pytest.mark.parametrize("admin_role", TrackRole.admins())
    def test_conference_secretary_and_track_chair_can_assign_admin_track_roles(
        self,
        user: User,
        conference: Conference,
        track_a: Track,
        admin_role: TrackRole,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        TrackRoleAssignment.objects.create(
            track=track_a,
            user=user,
            role=TrackRole.CHAIR,
        )

        ConferenceService.validate_can_assign_roles(
            user=user,
            conference=conference,
            track_roles={track_a: [admin_role]},
        )

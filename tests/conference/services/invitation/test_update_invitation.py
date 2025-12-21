from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    Keyword,
    Track,
    TrackRole,
)
from app.conference.services import ConferenceService, InvitationService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import ImmutableInvitation
from app.core.models import User
from app.utils.enums import Region

from .conftest import add_invitation_roles


@pytest.mark.django_db
class TestInvitationServiceUpdateInvitation:
    @pytest.fixture
    def pending_invitation(self, faker: Faker, conference: Conference) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="John",
            family_name="Doe",
            affiliation="University of Oxford",
            region_code=Region.GB.name,
            desired_paper_count=10,
        )

    @pytest.fixture
    def track_a(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    @pytest.fixture
    def track_b(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    @pytest.fixture
    def keyword_a(self, faker: Faker) -> Keyword:
        return Keyword.objects.create(text=faker.word())

    @pytest.fixture
    def keyword_b(self, faker: Faker) -> Keyword:
        return Keyword.objects.create(text=faker.word())

    @pytest.fixture
    def mock_validate_roles(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(ConferenceService, "validate_can_assign_roles")

    def test_happy_path(
        self,
        mocker: MockerFixture,
        global_admin: User,
        pending_invitation: Invitation,
        keyword_a: Keyword,
        keyword_b: Keyword,
        track_a: Track,
        track_b: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        add_invitation_roles(
            pending_invitation,
            conference_roles=[ConferenceRole.REVIEWER],
        )
        keyword_c = Keyword.objects.create(text="machine-learning")

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=global_admin,
            given_name="Jane",
            family_name="Smith",
            affiliation="MIT",
            region_code=Region.US.name,
            desired_paper_count=15,
            interested_keywords=[keyword_a, keyword_b, keyword_c],
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.SECRETARY],
            track_roles={
                track_a: [TrackRole.CHAIR],
                track_b: [TrackRole.SECRETARY],
            },
        )

        db_updated = Invitation.objects.get(pk=updated.pk)
        assert updated.given_name == db_updated.given_name == "Jane"
        assert updated.family_name == db_updated.family_name == "Smith"
        assert updated.affiliation == db_updated.affiliation == "MIT"
        assert updated.region_code == db_updated.region_code == Region.US.name
        assert updated.desired_paper_count == db_updated.desired_paper_count == 15
        assert set(updated.interested_keywords.all()) == {
            keyword_a,
            keyword_b,
            keyword_c,
        }

        conference_role_entries = list(updated.conference_role_entries.all())
        assert len(conference_role_entries) == 2
        assert {entry.role for entry in conference_role_entries} == {
            ConferenceRole.CHAIR,
            ConferenceRole.SECRETARY,
        }

        track_role_entries = list(updated.track_role_entries.all())
        assert len(track_role_entries) == 2
        assert {entry.track: entry.role for entry in track_role_entries} == {
            track_a: TrackRole.CHAIR,
            track_b: TrackRole.SECRETARY,
        }

        assert mock_validate_roles.call_args_list == [
            mocker.call(
                user=global_admin,
                conference=pending_invitation.conference,
                conference_roles=[ConferenceRole.REVIEWER],
                track_roles={},
            ),
            mocker.call(
                user=global_admin,
                conference=pending_invitation.conference,
                conference_roles=[ConferenceRole.CHAIR, ConferenceRole.SECRETARY],
                track_roles={
                    track_a: [TrackRole.CHAIR],
                    track_b: [TrackRole.SECRETARY],
                },
            ),
        ]

    def test_clear_keywords(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        keyword_a: Keyword,
        mock_validate_roles: MagicMock,
    ) -> None:
        pending_invitation.interested_keywords.add(keyword_a)

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=global_admin,
            interested_keywords=[],
        )

        assert not updated.interested_keywords.exists()

        assert mock_validate_roles.call_count == 2

    def test_remove_all_conference_roles(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        add_invitation_roles(
            pending_invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=global_admin,
            conference_roles=[],
        )

        assert not updated.conference_role_entries.exists()

        assert mock_validate_roles.call_count == 2

    def test_remove_all_track_roles(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        track_a: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        add_invitation_roles(
            pending_invitation,
            track_roles={track_a: [TrackRole.CHAIR]},
        )

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=global_admin,
            track_roles={},
        )

        assert not updated.track_role_entries.exists()

        assert mock_validate_roles.call_count == 2

    def test_duplicate_roles_are_deduplicated(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        track_a: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=global_admin,
            conference_roles=[
                ConferenceRole.REVIEWER,
                ConferenceRole.REVIEWER,
                ConferenceRole.CHAIR,
            ],
            track_roles={
                track_a: [TrackRole.REVIEWER, TrackRole.REVIEWER, TrackRole.CHAIR],
            },
        )

        assert updated.conference_role_entries.count() == 2
        assert updated.track_role_entries.count() == 2

        assert mock_validate_roles.call_count == 2

    def test_raises_immutable_invitation_for_accepted_invitation(
        self,
        faker: Faker,
        global_admin: User,
        conference: Conference,
        mock_validate_roles: MagicMock,  # noqa: ARG002
    ) -> None:
        accepted_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            accept_time=timezone.now(),
        )

        with pytest.raises(
            ImmutableInvitation,
            match="Cannot update accepted invitation",
        ):
            InvitationService.update_invitation(
                invitation_uid=accepted_invitation.uid,
                user=global_admin,
                given_name="New Name",
            )

    def test_rejected_invitation_can_be_updated(
        self,
        faker: Faker,
        global_admin: User,
        conference: Conference,
        mock_validate_roles: MagicMock,
    ) -> None:
        rejected_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            reject_time=timezone.now(),
        )

        updated = InvitationService.update_invitation(
            invitation_uid=rejected_invitation.uid,
            user=global_admin,
            given_name="Alice",
        )

        assert updated.given_name == "Alice"

        assert mock_validate_roles.call_count == 2

    def test_raises_does_not_exist_for_invalid_uid(self, global_admin: User) -> None:
        with pytest.raises(Invitation.DoesNotExist):
            InvitationService.update_invitation(
                invitation_uid=ULID(),
                user=global_admin,
            )

    def test_insufficient_permission_to_manage_current_roles(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        mock_validate_roles.side_effect = InsufficientRolePermission(
            "Cannot assign CHAIR role"
        )

        with pytest.raises(
            InsufficientRolePermission,
            match="You cannot manage this invitation",
        ):
            InvitationService.update_invitation(
                invitation_uid=pending_invitation.uid,
                user=global_admin,
                given_name="Alice",
            )

        mock_validate_roles.assert_called_once()

    def test_insufficient_permission_to_assign_new_roles(
        self,
        global_admin: User,
        pending_invitation: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        mock_validate_roles.side_effect = [
            None,
            InsufficientRolePermission("Cannot assign CHAIR role"),
        ]

        with pytest.raises(
            InsufficientRolePermission,
            match="Cannot assign CHAIR role",
        ):
            InvitationService.update_invitation(
                invitation_uid=pending_invitation.uid,
                user=global_admin,
                conference_roles=[ConferenceRole.CHAIR],
            )

        assert mock_validate_roles.call_count == 2

    def test_track_from_other_conference_rejected(
        self,
        faker: Faker,
        global_admin: User,
        pending_invitation: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        external_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )

        with pytest.raises(
            ValueError,
            match="do not belong to this conference",
        ):
            InvitationService.update_invitation(
                invitation_uid=pending_invitation.uid,
                user=global_admin,
                track_roles={external_track: [TrackRole.CHAIR]},
            )

        assert mock_validate_roles.call_count == 2

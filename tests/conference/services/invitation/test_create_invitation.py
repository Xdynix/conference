from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    Keyword,
    Track,
    TrackRole,
)
from app.conference.services import ConferenceService, InvitationService
from app.conference.services.invitation import DuplicateInvitation
from app.core.models import User
from app.utils.enums import Region
from tests.helpers import approx_now


@pytest.mark.django_db
class TestInvitationServiceCreateInvitation:
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
        return mocker.patch.object(ConferenceService, "validate_can_assign_roles")

    def test_happy_path(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        keyword_a: Keyword,
        keyword_b: Keyword,
        track_a: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitee_email = faker.email()

        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=invitee_email,
            given_name="John",
            family_name="Doe",
            affiliation="University of Oxford",
            region_code=Region.GB.name,
            desired_paper_count=10,
            interested_keywords=[keyword_a, keyword_b],
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

        db_invitation = Invitation.objects.get(pk=invitation.pk)
        assert invitation.conference == db_invitation.conference == conference
        assert invitation.inviter == db_invitation.inviter == inviter
        assert invitation.invitee_email == db_invitation.invitee_email == invitee_email
        assert invitation.invitee_user == db_invitation.invitee_user is None
        assert invitation.given_name == db_invitation.given_name == "John"
        assert invitation.family_name == db_invitation.family_name == "Doe"
        assert (
            invitation.affiliation
            == db_invitation.affiliation
            == "University of Oxford"
        )
        assert invitation.region_code == db_invitation.region_code == Region.GB.name
        assert invitation.desired_paper_count == db_invitation.desired_paper_count == 10
        assert invitation.status == Invitation.Status.PENDING
        assert invitation.create_time == db_invitation.create_time == approx_now()
        assert invitation.update_time == db_invitation.update_time == approx_now()
        assert invitation.accept_time == db_invitation.accept_time is None
        assert invitation.reject_time == db_invitation.reject_time is None
        assert (
            invitation.last_email_sent_time
            == db_invitation.last_email_sent_time
            is None
        )
        assert invitation.email_send_count == db_invitation.email_send_count == 0

        assert set(invitation.interested_keywords.all()) == {keyword_a, keyword_b}

        conference_role_entries = list(invitation.conference_role_entries.all())
        [conference_role_entry] = conference_role_entries
        assert conference_role_entry.role == ConferenceRole.REVIEWER

        track_role_entries = list(
            invitation.track_role_entries.select_related("track").all()
        )
        assert len(track_role_entries) == 2
        assert {entry.track for entry in track_role_entries} == {track_a}
        assert {entry.role for entry in track_role_entries} == {
            TrackRole.CHAIR,
            TrackRole.REVIEWER,
        }

        mock_validate_roles.assert_called_once_with(
            user=inviter,
            conference=conference,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

    def test_minimal_fields(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitee_email = faker.email()

        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=invitee_email,
        )

        assert invitation.conference == conference
        assert invitation.inviter == inviter
        assert invitation.invitee_email == invitee_email
        assert invitation.invitee_user is None
        assert invitation.given_name == ""
        assert invitation.family_name == ""
        assert invitation.affiliation == ""
        assert invitation.region_code == ""
        assert invitation.desired_paper_count == 5
        assert invitation.status == Invitation.Status.PENDING
        assert not invitation.interested_keywords.exists()
        assert not invitation.conference_role_entries.exists()
        assert not invitation.track_role_entries.exists()

        mock_validate_roles.assert_called_once_with(
            user=inviter,
            conference=conference,
            conference_roles=(),
            track_roles=None,
        )

    def test_conference_roles_only(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
            conference_roles=[ConferenceRole.REVIEWER, ConferenceRole.CHAIR],
        )

        conference_role_entries = list(invitation.conference_role_entries.all())
        assert len(conference_role_entries) == 2
        assert {entry.role for entry in conference_role_entries} == {
            ConferenceRole.REVIEWER,
            ConferenceRole.CHAIR,
        }
        assert not invitation.track_role_entries.exists()

        mock_validate_roles.assert_called_once_with(
            user=inviter,
            conference=conference,
            conference_roles=[ConferenceRole.REVIEWER, ConferenceRole.CHAIR],
            track_roles=None,
        )

    def test_track_roles_only(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        track_a: Track,
        track_b: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.CHAIR, TrackRole.SECRETARY],
            },
        )

        track_role_entries = list(
            invitation.track_role_entries.select_related("track").all()
        )
        assert len(track_role_entries) == 3
        assert {entry.track for entry in track_role_entries} == {track_a, track_b}

        track_a_roles = [
            entry.role for entry in track_role_entries if entry.track == track_a
        ]
        assert track_a_roles == [TrackRole.REVIEWER]

        track_b_roles = {
            entry.role for entry in track_role_entries if entry.track == track_b
        }
        assert track_b_roles == {TrackRole.CHAIR, TrackRole.SECRETARY}

        assert not invitation.conference_role_entries.exists()

        mock_validate_roles.assert_called_once_with(
            user=inviter,
            conference=conference,
            conference_roles=(),
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.CHAIR, TrackRole.SECRETARY],
            },
        )

    def test_duplicate_invitation_raises_error(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitee_email = faker.email()
        Invitation.objects.create(
            conference=conference,
            invitee_email=invitee_email,
        )

        # Attempt to create duplicate invitation.
        with pytest.raises(
            DuplicateInvitation,
            match="A pending invitation already exists for this conference and email",
        ):
            InvitationService.create_invitation(
                conference=conference,
                inviter=inviter,
                invitee_email=invitee_email,
            )

        mock_validate_roles.assert_called_once()

    def test_duplicate_invitation_case_insensitive(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitee_email = faker.email()
        Invitation.objects.create(
            conference=conference,
            invitee_email=invitee_email.lower(),
        )

        with pytest.raises(DuplicateInvitation):
            InvitationService.create_invitation(
                conference=conference,
                inviter=inviter,
                invitee_email=invitee_email.upper(),
            )

        mock_validate_roles.assert_called_once()

    def test_accepted_invitation_does_not_block_new_invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitee_email = faker.email()
        first_invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=invitee_email,
            accept_time=timezone.now(),
        )

        second_invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=invitee_email,
        )

        assert second_invitation != first_invitation
        assert second_invitation.status == Invitation.Status.PENDING

        mock_validate_roles.assert_called_once()

    def test_permission_validation_error_prevents_creation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        mock_validate_roles: MagicMock,
    ) -> None:
        mock_validate_roles.side_effect = ValueError("Permission denied")
        invitee_email = faker.email()

        with pytest.raises(ValueError, match="Permission denied"):
            InvitationService.create_invitation(
                conference=conference,
                inviter=inviter,
                invitee_email=invitee_email,
            )

        assert not Invitation.objects.filter(
            invitee_email__iexact=invitee_email
        ).exists()

    def test_duplicate_roles_are_deduplicated(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
        track_a: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
            conference_roles=[
                ConferenceRole.REVIEWER,
                ConferenceRole.REVIEWER,
                ConferenceRole.CHAIR,
            ],
            track_roles={
                track_a: [TrackRole.REVIEWER, TrackRole.REVIEWER, TrackRole.CHAIR],
            },
        )

        conference_role_entries = list(invitation.conference_role_entries.all())
        assert len(conference_role_entries) == 2
        assert {entry.role for entry in conference_role_entries} == {
            ConferenceRole.REVIEWER,
            ConferenceRole.CHAIR,
        }

        track_role_entries = list(invitation.track_role_entries.all())
        assert len(track_role_entries) == 2
        assert {entry.role for entry in track_role_entries} == {
            TrackRole.REVIEWER,
            TrackRole.CHAIR,
        }

        mock_validate_roles.assert_called_once()

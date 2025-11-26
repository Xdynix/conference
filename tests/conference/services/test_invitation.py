from collections.abc import Awaitable, Callable, Iterable, Mapping
from unittest.mock import MagicMock

import pytest
from django.core.signing import BadSignature
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService, InvitationService
from app.conference.services.conference import InsufficientRolePermission
from app.conference.services.invitation import DuplicateInvitation, ImmutableInvitation
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.enums import Region
from tests.helpers import approx_now, update_object


def add_invitation_roles(
    invitation: Invitation,
    *,
    conference_roles: Iterable[ConferenceRole] = (),
    track_roles: Mapping[Track, Iterable[TrackRole]] | None = None,
) -> None:
    for conference_role in conference_roles:
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=conference_role,
        )
    for track, roles in (track_roles or {}).items():
        for track_role in roles:
            InvitationTrackRoleEntry.objects.create(
                invitation=invitation,
                track=track,
                role=track_role,
            )


async def a_add_invitation_roles(
    invitation: Invitation,
    *,
    conference_roles: Iterable[ConferenceRole] = (),
    track_roles: Mapping[Track, Iterable[TrackRole]] | None = None,
) -> None:
    for conference_role in conference_roles:
        await InvitationConferenceRoleEntry.objects.acreate(
            invitation=invitation,
            role=conference_role,
        )
    for track, roles in (track_roles or {}).items():
        for track_role in roles:
            await InvitationTrackRoleEntry.objects.acreate(
                invitation=invitation,
                track=track,
                role=track_role,
            )


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def inviter(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def invitation(
    faker: Faker,
    conference: Conference,
) -> Invitation:
    return Invitation.objects.create(
        conference=conference,
        invitee_email=faker.email(),
    )


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
        assert len(conference_role_entries) == 1
        assert conference_role_entries[0].role == ConferenceRole.REVIEWER

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
    def user(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(
            user=user,
            role=GlobalRole.ADMIN,
        )
        return user

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
        user: User,
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
            user=user,
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
                user=user,
                conference=pending_invitation.conference,
                conference_roles=[ConferenceRole.REVIEWER],
                track_roles={},
            ),
            mocker.call(
                user=user,
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
        user: User,
        pending_invitation: Invitation,
        keyword_a: Keyword,
        mock_validate_roles: MagicMock,
    ) -> None:
        pending_invitation.interested_keywords.add(keyword_a)

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=user,
            interested_keywords=[],
        )

        assert not updated.interested_keywords.exists()

        assert mock_validate_roles.call_count == 2

    def test_remove_all_conference_roles(
        self,
        user: User,
        pending_invitation: Invitation,
        mock_validate_roles: MagicMock,
    ) -> None:
        add_invitation_roles(
            pending_invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=user,
            conference_roles=[],
        )

        assert not updated.conference_role_entries.exists()

        assert mock_validate_roles.call_count == 2

    def test_remove_all_track_roles(
        self,
        user: User,
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
            user=user,
            track_roles={},
        )

        assert not updated.track_role_entries.exists()

        assert mock_validate_roles.call_count == 2

    def test_duplicate_roles_are_deduplicated(
        self,
        user: User,
        pending_invitation: Invitation,
        track_a: Track,
        mock_validate_roles: MagicMock,
    ) -> None:
        updated = InvitationService.update_invitation(
            invitation_uid=pending_invitation.uid,
            user=user,
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
        user: User,
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
                user=user,
                given_name="New Name",
            )

    def test_rejected_invitation_can_be_updated(
        self,
        faker: Faker,
        user: User,
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
            user=user,
            given_name="Alice",
        )

        assert updated.given_name == "Alice"

        assert mock_validate_roles.call_count == 2

    def test_raises_does_not_exist_for_invalid_uid(self, user: User) -> None:
        with pytest.raises(Invitation.DoesNotExist):
            InvitationService.update_invitation(
                invitation_uid=ULID(),
                user=user,
            )

    def test_insufficient_permission_to_manage_current_roles(
        self,
        user: User,
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
                user=user,
                given_name="Alice",
            )

        mock_validate_roles.assert_called_once()

    def test_insufficient_permission_to_assign_new_roles(
        self,
        user: User,
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
                user=user,
                conference_roles=[ConferenceRole.CHAIR],
            )

        assert mock_validate_roles.call_count == 2

    def test_track_from_other_conference_rejected(
        self,
        faker: Faker,
        user: User,
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
                user=user,
                track_roles={external_track: [TrackRole.CHAIR]},
            )

        assert mock_validate_roles.call_count == 2


@pytest.mark.django_db
class TestInvitationServiceGetInvitationRoles:
    def test_no_roles(self, invitation: Invitation) -> None:
        conference_roles, track_roles = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert track_roles == {}

    def test_conference_roles_only(self, invitation: Invitation) -> None:
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        conference_roles, track_roles = InvitationService.get_invitation_roles(
            invitation
        )

        assert set(conference_roles) == {ConferenceRole.CHAIR, ConferenceRole.REVIEWER}
        assert track_roles == {}

    def test_track_roles_only(self, invitation: Invitation, track: Track) -> None:
        add_invitation_roles(
            invitation,
            track_roles={track: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert set(track_roles_result) == {track}
        assert set(track_roles_result[track]) == {
            TrackRole.CHAIR,
            TrackRole.REVIEWER,
        }

    def test_mixed_conference_and_track_roles(
        self,
        faker: Faker,
        invitation: Invitation,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.SECRETARY],
            track_roles={
                track: [TrackRole.CHAIR, TrackRole.REVIEWER],
                track_b: [TrackRole.SECRETARY],
            },
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == [ConferenceRole.SECRETARY]
        assert set(track_roles_result) == {track, track_b}
        assert set(track_roles_result[track]) == {
            TrackRole.CHAIR,
            TrackRole.REVIEWER,
        }
        assert track_roles_result[track_b] == [TrackRole.SECRETARY]

    def test_multiple_tracks_with_roles(
        self,
        faker: Faker,
        invitation: Invitation,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        track_c = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            track_roles={
                track: [TrackRole.CHAIR],
                track_b: [TrackRole.REVIEWER],
                track_c: [TrackRole.SECRETARY],
            },
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert set(track_roles_result) == {track, track_b, track_c}
        assert track_roles_result[track] == [TrackRole.CHAIR]
        assert track_roles_result[track_b] == [TrackRole.REVIEWER]
        assert track_roles_result[track_c] == [TrackRole.SECRETARY]


@pytest.mark.django_db
class TestInvitationServiceGetInvitationToken:
    def test_happy_path(self, invitation: Invitation) -> None:
        token = InvitationService.get_invitation_token(invitation)

        assert isinstance(token, str)
        assert len(token) > 0
        assert ":" in token

    def test_token_is_deterministic(self, invitation: Invitation) -> None:
        token1 = InvitationService.get_invitation_token(invitation)
        token2 = InvitationService.get_invitation_token(invitation)

        assert token1 == token2

    def test_different_invitations_produce_different_tokens(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        invitation1 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        invitation2 = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )

        token1 = InvitationService.get_invitation_token(invitation1)
        token2 = InvitationService.get_invitation_token(invitation2)

        assert token1 != token2


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceRetrieveInvitation:
    async def test_happy_path(self, invitation: Invitation) -> None:
        token = InvitationService.get_invitation_token(invitation)

        result = await InvitationService.retrieve_invitation(token)

        assert result == invitation

    async def test_returns_none_for_invalid_token(self) -> None:
        invalid_token = "invalid:token:signature"

        result = await InvitationService.retrieve_invitation(invalid_token)

        assert result is None

    async def test_returns_none_for_tampered_token(
        self,
        invitation: Invitation,
    ) -> None:
        token = InvitationService.get_invitation_token(invitation)
        tampered_token = token[:-6] + "foobar"

        result = await InvitationService.retrieve_invitation(tampered_token)

        assert result is None

    async def test_returns_none_for_nonexistent_invitation(
        self,
        mocker: MockerFixture,
    ) -> None:
        mock_unsign = mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            return_value=ULID(),
        )
        fake_token = "fake:token"

        result = await InvitationService.retrieve_invitation(fake_token)

        assert result is None
        mock_unsign.assert_called_once_with(fake_token)

    async def test_handles_bad_signature_exception(
        self,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            InvitationService.token_signer,
            "unsign",
            side_effect=BadSignature("Invalid signature"),
        )

        result = await InvitationService.retrieve_invitation("bad:token")

        assert result is None


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceRedeemInvitation:
    @pytest.fixture
    def invitee(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    def test_happy_path(self, invitee: User, invitation: Invitation) -> None:
        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_returns_false_when_already_accepted(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        update_object(
            invitation,
            invitee_user=invitee,
            accept_time=timezone.now(),
        )
        original_accept_time = invitation.accept_time
        original_update_time = invitation.update_time

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is False

        invitation.refresh_from_db()
        assert invitation.accept_time == original_accept_time
        assert invitation.update_time == original_update_time

    def test_returns_true_when_already_rejected(
        self,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        update_object(invitation, reject_time=timezone.now())

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_assigns_conference_roles(
        self,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=ConferenceRole.CHAIR,
        ).exists()
        assert ConferenceRoleAssignment.objects.filter(
            user=invitee,
            conference=conference,
            role=ConferenceRole.REVIEWER,
        ).exists()

    def test_assigns_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        track1 = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        track2 = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            track_roles={
                track1: [TrackRole.SECRETARY, TrackRole.REVIEWER],
                track2: [TrackRole.SECRETARY],
            },
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=TrackRole.SECRETARY,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track1,
            role=TrackRole.REVIEWER,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            user=invitee,
            track=track2,
            role=TrackRole.SECRETARY,
        ).exists()

    def test_ignores_duplicate_role_assignments(
        self,
        conference: Conference,
        track: Track,
        invitee: User,
        invitation: Invitation,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            user=invitee,
            conference=conference,
            role=ConferenceRole.CHAIR,
        )
        TrackRoleAssignment.objects.create(
            user=invitee,
            track=track,
            role=TrackRole.SECRETARY,
        )
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR],
            track_roles={track: [TrackRole.SECRETARY]},
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert (
            ConferenceRoleAssignment.objects.filter(
                user=invitee,
                conference=conference,
                role=ConferenceRole.CHAIR,
            ).count()
            == 1
        )
        assert (
            TrackRoleAssignment.objects.filter(
                user=invitee,
                track=track,
                role=TrackRole.SECRETARY,
            ).count()
            == 1
        )


InvitationFactory = Callable[..., Awaitable[Invitation]]


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceVisibleInvitations:
    @pytest.fixture
    def make_invitation(
        self,
        faker: Faker,
        conference: Conference,
    ) -> InvitationFactory:
        async def make_invitation() -> Invitation:
            return await Invitation.objects.acreate(
                conference=conference,
                invitee_email=faker.email(),
            )

        return make_invitation

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
    def track_c(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    async def test_superuser_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        superuser = await User.objects.acreate_superuser(username=faker.user_name())
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(conference, superuser)

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    async def test_global_role_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        global_role: GlobalRole,
    ) -> None:
        user = await User.objects.acreate_user(username=faker.user_name())
        await GlobalRoleAssignment.objects.acreate(user=user, role=global_role)
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(conference, user)

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        conference_role: ConferenceRole,
    ) -> None:
        conference_admin = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            user=conference_admin,
            conference=conference,
            role=conference_role,
        )
        invitation1 = await make_invitation()
        invitation2 = await make_invitation()

        result = await InvitationService.visible_invitations(
            conference,
            conference_admin,
        )

        assert await result.acount() == 2
        assert {i async for i in result} == {invitation1, invitation2}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_invitation_with_only_their_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation, track_roles={track_a: [TrackRole.REVIEWER]}
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_mixed_track_invitation(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_other_tracks_invitation(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation, track_roles={track_b: [TrackRole.REVIEWER]}
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_invitation_with_conference_role(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=track_role,
        )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_does_not_see_invitation_with_no_role(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_role: TrackRole,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=track_role,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    async def test_conference_reviewer_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await ConferenceRoleAssignment.objects.acreate(
            user=reviewer,
            conference=conference,
            role=ConferenceRole.REVIEWER,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, reviewer)

        assert await result.acount() == 0

    async def test_track_reviewer_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
    ) -> None:
        reviewer = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=reviewer,
            track=track_a,
            role=TrackRole.REVIEWER,
        )
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, reviewer)

        assert await result.acount() == 0

    async def test_non_admin_user_sees_no_invitations(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
    ) -> None:
        regular_user = await User.objects.acreate_user(username=faker.user_name())
        await make_invitation()

        result = await InvitationService.visible_invitations(conference, regular_user)

        assert await result.acount() == 0

    async def test_multiple_administered_tracks_sees_invitation_with_one_of_tracks(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b, track_c):
            await TrackRoleAssignment.objects.acreate(
                user=track_admin,
                track=track,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    async def test_multiple_administered_tracks_sees_invitation_with_subset_of_tracks(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b, track_c):
            await TrackRoleAssignment.objects.acreate(
                user=track_admin,
                track=track,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_c: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 1
        assert {i async for i in result} == {invitation}

    async def test_multiple_administered_tracks_does_not_see_invitation_with_tracks_outside_set(  # noqa: E501
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
        track_c: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        for track in (track_a, track_b):
            await TrackRoleAssignment.objects.acreate(
                user=track_admin,
                track=track,
                role=TrackRole.CHAIR,
            )
        invitation = await make_invitation()
        await a_add_invitation_roles(
            invitation,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_c: [TrackRole.REVIEWER],
            },
        )

        result = await InvitationService.visible_invitations(conference, track_admin)

        assert await result.acount() == 0

    async def test_returns_exact_visible_set_with_no_duplicates(
        self,
        faker: Faker,
        conference: Conference,
        make_invitation: InvitationFactory,
        track_a: Track,
        track_b: Track,
    ) -> None:
        track_admin = await User.objects.acreate_user(username=faker.user_name())
        await TrackRoleAssignment.objects.acreate(
            user=track_admin,
            track=track_a,
            role=TrackRole.CHAIR,
        )

        visible_invitation1 = await make_invitation()
        await a_add_invitation_roles(
            visible_invitation1,
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        visible_invitation2 = await make_invitation()
        await a_add_invitation_roles(
            visible_invitation2,
            track_roles={track_a: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

        hidden_invitation_mixed_tracks = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_mixed_tracks,
            track_roles={
                track_a: [TrackRole.REVIEWER],
                track_b: [TrackRole.REVIEWER],
            },
        )

        hidden_invitation_conference_role = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_conference_role,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles={track_a: [TrackRole.REVIEWER]},
        )

        hidden_invitation_other_track = await make_invitation()
        await a_add_invitation_roles(
            hidden_invitation_other_track,
            track_roles={track_b: [TrackRole.REVIEWER]},
        )

        result = await InvitationService.visible_invitations(conference, track_admin)
        result_list = [invitation async for invitation in result]

        assert len(result_list) == 2
        assert len(set(result_list)) == 2
        assert set(result_list) == {visible_invitation1, visible_invitation2}

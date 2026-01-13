import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    Keyword,
    Track,
    TrackRole,
    TrackRoleAssignment,
    UserConferenceProfile,
)
from app.conference.services import InvitationService
from app.core.models import User
from tests.helpers import approx_now, update_object

from .conftest import add_invitation_roles


@pytest.mark.django_db(transaction=True)
class TestInvitationServiceRedeemInvitation:
    @pytest.fixture
    def invitee(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    def test_happy_path(self, invitation: Invitation, invitee: User) -> None:
        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.state == Invitation.State.ACCEPTED

    def test_returns_false_when_already_accepted(
        self,
        invitation: Invitation,
        invitee: User,
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
        invitation: Invitation,
        invitee: User,
    ) -> None:
        update_object(invitation, reject_time=timezone.now())

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        invitation.refresh_from_db()
        assert invitation.invitee_user_id == invitee.id
        assert invitation.accept_time == approx_now()
        assert invitation.state == Invitation.State.ACCEPTED

    def test_assigns_conference_roles(
        self,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=invitee,
            role=ConferenceRole.CHAIR,
        ).exists()
        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=invitee,
            role=ConferenceRole.REVIEWER,
        ).exists()

    def test_assigns_track_roles(
        self,
        faker: Faker,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
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
            track=track1,
            user=invitee,
            role=TrackRole.SECRETARY,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            track=track1,
            user=invitee,
            role=TrackRole.REVIEWER,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            track=track2,
            user=invitee,
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
            conference=conference,
            user=invitee,
            role=ConferenceRole.CHAIR,
        )
        TrackRoleAssignment.objects.create(
            track=track,
            user=invitee,
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
                conference=conference,
                user=invitee,
                role=ConferenceRole.CHAIR,
            ).count()
            == 1
        )
        assert (
            TrackRoleAssignment.objects.filter(
                track=track,
                user=invitee,
                role=TrackRole.SECRETARY,
            ).count()
            == 1
        )

    def test_raises_when_track_not_in_conference(
        self,
        faker: Faker,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        other_track = Track.objects.create(
            conference=other_conference,
            display_name=faker.word(),
        )
        invitation.track_role_entries.create(
            track=other_track,
            role=TrackRole.REVIEWER,
        )

        with pytest.raises(RuntimeError, match="track role does not belong to"):
            InvitationService.redeem_invitation(invitation, invitee)

    def test_inactive_track_roles_not_assigned(
        self,
        faker: Faker,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        active_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        inactive_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        add_invitation_roles(
            invitation,
            track_roles={
                active_track: [TrackRole.CHAIR],
                inactive_track: [TrackRole.SECRETARY],
            },
        )

        result = InvitationService.redeem_invitation(invitation, invitee)
        assert result is True

        assert TrackRoleAssignment.objects.filter(
            track=active_track,
            user=invitee,
            role=TrackRole.CHAIR,
        ).exists()
        assert not TrackRoleAssignment.objects.filter(
            track=inactive_track,
            user=invitee,
            role=TrackRole.SECRETARY,
        ).exists()

    def test_creates_conference_profile(
        self,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        update_object(invitation, desired_paper_count=10)

        InvitationService.redeem_invitation(invitation, invitee)

        profile = UserConferenceProfile.objects.get(user=invitee, conference=conference)
        assert profile.desired_paper_count == 10

    def test_creates_conference_profile_with_keywords(
        self,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        kw1 = Keyword.objects.create(text="machine-learning")
        kw2 = Keyword.objects.create(text="deep-learning")
        invitation.interested_keywords.set([kw1, kw2])

        InvitationService.redeem_invitation(invitation, invitee)

        profile = UserConferenceProfile.objects.get(user=invitee, conference=conference)
        assert set(profile.interested_keywords.all()) == {kw1, kw2}

    def test_does_not_overwrite_existing_profile(
        self,
        conference: Conference,
        invitation: Invitation,
        invitee: User,
    ) -> None:
        kw1 = Keyword.objects.create(text="existing-keyword")
        kw2 = Keyword.objects.create(text="invitation-keyword")
        existing_profile = UserConferenceProfile.objects.create(
            user=invitee,
            conference=conference,
            desired_paper_count=20,
        )
        existing_profile.interested_keywords.set([kw1])

        update_object(invitation, desired_paper_count=10)
        invitation.interested_keywords.set([kw2])

        InvitationService.redeem_invitation(invitation, invitee)

        existing_profile.refresh_from_db()
        assert existing_profile.desired_paper_count == 20
        assert list(existing_profile.interested_keywords.all()) == [kw1]

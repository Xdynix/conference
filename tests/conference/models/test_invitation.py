import pytest
from django.db import IntegrityError
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Track,
    TrackRole,
)
from app.core.models import User


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.mark.django_db
class TestInvitation:
    def test_str_pending(self) -> None:
        conference = Conference(name="CBPK-2020")
        invitation = Invitation(
            invitee_email="alice@example.com",
            conference=conference,
        )
        assert str(invitation) == "alice@example.com → CBPK-2020 (Pending)"

    def test_str_accepted(self) -> None:
        conference = Conference(name="CBPK-2020")
        invitation = Invitation(
            invitee_email="alice@example.com",
            conference=conference,
            accept_time=timezone.now(),
        )
        assert str(invitation) == "alice@example.com → CBPK-2020 (Accepted)"

    def test_str_rejected(self) -> None:
        conference = Conference(name="CBPK-2020")
        invitation = Invitation(
            invitee_email="alice@example.com",
            conference=conference,
            reject_time=timezone.now(),
        )
        assert str(invitation) == "alice@example.com → CBPK-2020 (Rejected)"

    def test_state_pending(self) -> None:
        invitation = Invitation()
        assert invitation.state == Invitation.State.PENDING

    def test_state_accepted(self) -> None:
        invitation = Invitation(accept_time=timezone.now())
        assert invitation.state == Invitation.State.ACCEPTED

    def test_state_rejected(self) -> None:
        invitation = Invitation(reject_time=timezone.now())
        assert invitation.state == Invitation.State.REJECTED

    def test_state_accepted_takes_precedence(self) -> None:
        invitation = Invitation(
            accept_time=timezone.now(),
            reject_time=timezone.now(),
        )
        assert invitation.state == Invitation.State.ACCEPTED

    def test_is_mutable_pending(self) -> None:
        invitation = Invitation()
        assert invitation.mutable is True

    def test_is_mutable_rejected(self) -> None:
        invitation = Invitation(reject_time=timezone.now())
        assert invitation.mutable is True

    def test_is_mutable_accepted(self) -> None:
        invitation = Invitation(accept_time=timezone.now())
        assert invitation.mutable is False

    def test_delete_inviter_will_not_cascade(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        inviter = User.objects.create(username=faker.user_name())
        invitation = Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=faker.email(),
        )

        inviter.delete()

        assert Invitation.objects.filter(pk=invitation.pk).exists()
        invitation.refresh_from_db()
        assert invitation.inviter is None

    def test_unique_pending_invitation_same_email(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        email = faker.email()

        Invitation.objects.create(
            conference=conference,
            invitee_email=email,
        )

        with pytest.raises(IntegrityError):
            Invitation.objects.create(
                conference=conference,
                invitee_email=email,
            )

    def test_unique_pending_invitation_case_insensitive(
        self,
        conference: Conference,
    ) -> None:
        Invitation.objects.create(
            conference=conference,
            invitee_email="alice@example.com",
        )

        with pytest.raises(IntegrityError):
            Invitation.objects.create(
                conference=conference,
                invitee_email="ALICE@example.com",
            )

    def test_unique_pending_allows_different_conference(self, faker: Faker) -> None:
        email = faker.email()
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        Invitation.objects.create(
            conference=conference1,
            invitee_email=email,
        )
        Invitation.objects.create(
            conference=conference2,
            invitee_email=email,
        )

    def test_unique_pending_allows_accepted_invitation(
        self,
        faker: Faker,
        conference: Conference,
    ) -> None:
        email = faker.email()

        Invitation.objects.create(
            conference=conference,
            invitee_email=email,
            accept_time=timezone.now(),
        )
        Invitation.objects.create(
            conference=conference,
            invitee_email=email,
        )


@pytest.mark.django_db
class TestInvitationConferenceRoleEntry:
    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )

    def test_str(self, invitation: Invitation) -> None:
        entry = InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.SECRETARY,
        )
        assert "Secretary" in str(entry)

    def test_unique_invitation_role(self, invitation: Invitation) -> None:
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=ConferenceRole.SECRETARY,
        )

        with pytest.raises(IntegrityError):
            InvitationConferenceRoleEntry.objects.create(
                invitation=invitation,
                role=ConferenceRole.SECRETARY,
            )


@pytest.mark.django_db
class TestInvitationTrackRoleEntry:
    @pytest.fixture
    def track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )

    def test_str(self, invitation: Invitation, track: Track) -> None:
        entry = InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track,
            role=TrackRole.REVIEWER,
        )
        assert "Reviewer" in str(entry)

    def test_unique_invitation_track_role(
        self,
        invitation: Invitation,
        track: Track,
    ) -> None:
        InvitationTrackRoleEntry.objects.create(
            invitation=invitation,
            track=track,
            role=TrackRole.REVIEWER,
        )

        with pytest.raises(IntegrityError):
            InvitationTrackRoleEntry.objects.create(
                invitation=invitation,
                track=track,
                role=TrackRole.REVIEWER,
            )

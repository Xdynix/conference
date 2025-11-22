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


@pytest.fixture
def inviter(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


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

    def test_status_pending(self) -> None:
        invitation = Invitation()
        assert invitation.status == Invitation.Status.PENDING

    def test_status_accepted(self) -> None:
        invitation = Invitation(accept_time=timezone.now())
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_status_rejected(self) -> None:
        invitation = Invitation(reject_time=timezone.now())
        assert invitation.status == Invitation.Status.REJECTED

    def test_status_accepted_takes_precedence(self) -> None:
        invitation = Invitation(
            accept_time=timezone.now(),
            reject_time=timezone.now(),
        )
        assert invitation.status == Invitation.Status.ACCEPTED

    def test_is_mutable_pending(self) -> None:
        invitation = Invitation()
        assert invitation.is_mutable() is True

    def test_is_mutable_rejected(self) -> None:
        invitation = Invitation(reject_time=timezone.now())
        assert invitation.is_mutable() is True

    def test_is_mutable_accepted(self) -> None:
        invitation = Invitation(accept_time=timezone.now())
        assert invitation.is_mutable() is False

    def test_unique_pending_invitation_same_email(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> None:
        email = faker.email()

        Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=email,
        )

        with pytest.raises(IntegrityError):
            Invitation.objects.create(
                conference=conference,
                inviter=inviter,
                invitee_email=email,
            )

    def test_unique_pending_invitation_case_insensitive(
        self,
        conference: Conference,
        inviter: User,
    ) -> None:
        Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email="alice@example.com",
        )

        with pytest.raises(IntegrityError):
            Invitation.objects.create(
                conference=conference,
                inviter=inviter,
                invitee_email="ALICE@example.com",
            )

    def test_unique_pending_allows_different_conference(
        self,
        faker: Faker,
        inviter: User,
    ) -> None:
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
            inviter=inviter,
            invitee_email=email,
        )
        Invitation.objects.create(
            conference=conference2,
            inviter=inviter,
            invitee_email=email,
        )

    def test_unique_pending_allows_accepted_invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> None:
        email = faker.email()

        Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=email,
            accept_time=timezone.now(),
        )
        Invitation.objects.create(
            conference=conference,
            inviter=inviter,
            invitee_email=email,
        )


@pytest.mark.django_db
class TestInvitationConferenceRoleEntry:
    @pytest.fixture
    def invitation(
        self,
        faker: Faker,
        conference: Conference,
        inviter: User,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            inviter=inviter,
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
        inviter: User,
    ) -> Invitation:
        return Invitation.objects.create(
            conference=conference,
            inviter=inviter,
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

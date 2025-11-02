import pytest
from django.db import IntegrityError
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationTrackEntry,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
    TrackRoleAssignment,
    UserConferenceProfile,
    UserProfile,
)
from app.core.models import User


class TestKeyword:
    def test_str(self) -> None:
        assert str(Keyword(text="Foobar")) == "Foobar"


class TestKeywordSet:
    def test_str(self) -> None:
        assert str(KeywordSet(name="Foobar")) == "Foobar"


class TestConference:
    def test_str(self) -> None:
        assert str(Conference(name="CBPK-2020")) == "CBPK-2020"


class TestConferenceRole:
    def test_str(self) -> None:
        assert str(ConferenceRole(name="chair")) == "chair"


class TestConferenceRoleAssignment:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        user = User(username="alice")
        role = ConferenceRole(name="chair")
        assert (
            str(ConferenceRoleAssignment(conference=conference, user=user, role=role))
            == "[CBPK-2020] chair: alice"
        )


class TestTrack:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        track = Track(conference=conference, display_name="Machine Learning")
        assert str(track) == "CBPK-2020 - Machine Learning"


class TestTrackRole:
    def test_str(self) -> None:
        assert str(TrackRole(name="reviewer")) == "reviewer"


class TestTrackRoleAssignment:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        track = Track(conference=conference, display_name="Machine Learning")
        user = User(username="bob")
        role = TrackRole(name="reviewer")
        assert (
            str(TrackRoleAssignment(track=track, user=user, role=role))
            == "[CBPK-2020 - Machine Learning] reviewer: bob"
        )


class TestUserProfile:
    def test_str(self) -> None:
        user = User(username="alice")
        profile = UserProfile(user=user)
        assert str(profile) == "alice's profile"


class TestUserConferenceProfile:
    def test_str(self) -> None:
        user = User(username="alice")
        conference = Conference(name="CBPK-2020")
        profile = UserConferenceProfile(user=user, conference=conference)
        assert str(profile) == "alice @ CBPK-2020"


@pytest.mark.django_db
class TestInvitation:
    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def inviter(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

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
class TestInvitationTrackEntry:
    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def inviter(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

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

    @pytest.fixture
    def reviewer_role(self) -> TrackRole:
        return TrackRole.objects.create(
            name="reviewer",
            display_name="Track Reviewer",
        )

    @pytest.fixture
    def chair_role(self) -> TrackRole:
        return TrackRole.objects.create(
            name="chair",
            display_name="Track Chair",
        )

    def test_str_with_single_role(
        self,
        invitation: Invitation,
        track: Track,
        reviewer_role: TrackRole,
    ) -> None:
        entry = InvitationTrackEntry.objects.create(
            invitation=invitation,
            track=track,
        )
        entry.roles.add(reviewer_role)

        str_repr = str(entry)
        assert "reviewer" in str_repr

    def test_str_with_multiple_roles(
        self,
        invitation: Invitation,
        track: Track,
        reviewer_role: TrackRole,
        chair_role: TrackRole,
    ) -> None:
        entry = InvitationTrackEntry.objects.create(
            invitation=invitation,
            track=track,
        )
        entry.roles.add(chair_role, reviewer_role)

        str_repr = str(entry)
        assert "chair" in str_repr
        assert "reviewer" in str_repr

    def test_unique_invitation_track(
        self,
        invitation: Invitation,
        track: Track,
    ) -> None:
        InvitationTrackEntry.objects.create(
            invitation=invitation,
            track=track,
        )

        with pytest.raises(IntegrityError):
            InvitationTrackEntry.objects.create(
                invitation=invitation,
                track=track,
            )

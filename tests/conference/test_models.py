from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
    UserProfile,
)
from app.core.models import User


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

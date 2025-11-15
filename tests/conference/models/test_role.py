from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import User


class TestConferenceRoleAssignment:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        user = User(username="alice")
        role = ConferenceRole.CHAIR
        assignment = ConferenceRoleAssignment(
            conference=conference,
            user=user,
            role=role,
        )
        assert str(assignment) == "[CBPK-2020] Chair: alice"


class TestTrackRoleAssignment:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        track = Track(conference=conference, display_name="Machine Learning")
        user = User(username="bob")
        role = TrackRole.REVIEWER
        assignment = TrackRoleAssignment(track=track, user=user, role=role)
        assert str(assignment) == "[CBPK-2020 - Machine Learning] Reviewer: bob"

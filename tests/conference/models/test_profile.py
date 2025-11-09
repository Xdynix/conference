from app.conference.models import (
    Conference,
    UserConferenceProfile,
    UserProfile,
)
from app.core.models import User


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

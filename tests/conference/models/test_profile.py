from app.conference.models import Conference, Profile, UserConferenceProfile
from app.core.models import User


class TestProfile:
    def test_str(self) -> None:
        user = User(username="alice")
        profile = Profile(user=user)
        assert str(profile) == "alice's profile"


class TestUserConferenceProfile:
    def test_str(self) -> None:
        user = User(username="alice")
        conference = Conference(name="CBPK-2020")
        profile = UserConferenceProfile(user=user, conference=conference)
        assert str(profile) == "alice @ CBPK-2020"

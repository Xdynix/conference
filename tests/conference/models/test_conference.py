from app.conference.models import (
    Conference,
    Track,
)


class TestConference:
    def test_str(self) -> None:
        assert str(Conference(name="CBPK-2020")) == "CBPK-2020"


class TestTrack:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        track = Track(conference=conference, display_name="Machine Learning")
        assert str(track) == "CBPK-2020 - Machine Learning"

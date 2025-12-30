from app.conference.models import AcceptanceLetter, Conference, Paper, Track
from app.core.models import User


class TestAcceptanceLetter:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2024")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        letter = AcceptanceLetter(paper=paper)
        assert str(letter) == "Acceptance letter for [CBPK-2024 - Main] PAPER-001"

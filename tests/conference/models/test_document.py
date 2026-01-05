from app.conference.models import (
    AcceptanceLetter,
    Conference,
    Paper,
    Receipt,
    Registration,
    Track,
)
from app.core.models import User


class TestAcceptanceLetter:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2024")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        letter = AcceptanceLetter(paper=paper)
        assert str(letter) == "Acceptance letter for [CBPK-2024 - Main] PAPER-001"


class TestReceipt:
    def test_str_with_name(self) -> None:
        conference = Conference(name="CBPK-2024")
        user = User(username="alice")
        registration = Registration(
            conference=conference,
            user=user,
            given_name="Alice",
            family_name="Smith",
            reference_code="12345678",
        )
        receipt = Receipt(registration=registration)
        assert str(receipt) == "Receipt for Alice Smith"

    def test_str_with_reference_code(self) -> None:
        conference = Conference(name="CBPK-2024")
        user = User(username="alice")
        registration = Registration(
            conference=conference,
            user=user,
            given_name="",
            family_name="",
            reference_code="12345678",
        )
        receipt = Receipt(registration=registration)
        assert str(receipt) == "Receipt for 12345678"

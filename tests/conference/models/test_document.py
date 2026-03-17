from app.conference.models import (
    AcceptanceLetter,
    Conference,
    ConferenceFile,
    Paper,
    PaperProof,
    Receipt,
    Registration,
    Track,
)
from app.conference.models.document import (
    acceptance_letter_path,
    conference_file_path,
    paper_proof_path,
    receipt_path,
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


class TestAcceptanceLetterPath:
    def test_generates_path(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        letter = AcceptanceLetter(paper=paper)
        path = acceptance_letter_path(letter, "document.pdf")
        assert path == "CONF-2025/PAPER-001/acceptance-letter.pdf"

    def test_lowercases_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        letter = AcceptanceLetter(paper=paper)
        path = acceptance_letter_path(letter, "document.PDF")
        assert path.endswith(".pdf")

    def test_truncates_long_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        letter = AcceptanceLetter(paper=paper)
        path = acceptance_letter_path(letter, "file.very-long-extension")
        ext = path.split(".")[-1]
        assert len(ext) < 10


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


class TestReceiptPath:
    def test_generates_path(self) -> None:
        conference = Conference(name="CONF-2025")
        user = User(username="alice")
        registration = Registration(
            conference=conference,
            user=user,
            reference_code="12345678",
        )
        path = receipt_path(Receipt(registration=registration), "receipt.pdf")
        assert path == f"CONF-2025/receipts/{registration.uid}.pdf"

    def test_lowercases_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        user = User(username="alice")
        registration = Registration(
            conference=conference,
            user=user,
            reference_code="12345678",
        )
        path = receipt_path(Receipt(registration=registration), "receipt.PDF")
        assert path.endswith(".pdf")

    def test_truncates_long_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        user = User(username="alice")
        registration = Registration(
            conference=conference,
            user=user,
            reference_code="12345678",
        )
        path = receipt_path(
            Receipt(registration=registration), "file.very-long-extension"
        )
        ext = path.split(".")[-1]
        assert len(ext) < 10


class TestConferenceFile:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2024")
        cf = ConferenceFile(conference=conference, name="payment-form")
        assert str(cf) == "payment-form (CBPK-2024)"


class TestPaperProof:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2024")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        proof = PaperProof(
            paper=paper,
            recipient_name="Alice",
            recipient_email="a@b.com",
        )
        assert str(proof) == "Proof for [CBPK-2024 - Main] PAPER-001"


class TestPaperProofPath:
    def test_generates_path(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        proof = PaperProof(
            paper=paper,
            recipient_name="Alice",
            recipient_email="a@b.com",
        )
        path = paper_proof_path(proof, "edited.pdf")
        assert path == "CONF-2025/PAPER-001/proof.pdf"

    def test_lowercases_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        proof = PaperProof(
            paper=paper,
            recipient_name="Alice",
            recipient_email="a@b.com",
        )
        path = paper_proof_path(proof, "edited.PDF")
        assert path.endswith(".pdf")

    def test_truncates_long_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        track = Track(conference=conference, display_name="Main")
        user = User(username="alice")
        paper = Paper(conference=conference, track=track, code="PAPER-001", owner=user)
        proof = PaperProof(
            paper=paper,
            recipient_name="Alice",
            recipient_email="a@b.com",
        )
        path = paper_proof_path(proof, "file.very-long-extension")
        ext = path.split(".")[-1]
        assert len(ext) < 10


class TestConferenceFilePath:
    def test_generates_path(self) -> None:
        conference = Conference(name="CONF-2025")
        cf = ConferenceFile(conference=conference, name="payment-form")
        path = conference_file_path(cf, "Payment Form.pdf")
        assert path == "CONF-2025/files/payment-form.pdf"

    def test_lowercases_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        cf = ConferenceFile(conference=conference, name="instructions")
        path = conference_file_path(cf, "doc.PDF")
        assert path.endswith(".pdf")

    def test_truncates_long_extension(self) -> None:
        conference = Conference(name="CONF-2025")
        cf = ConferenceFile(conference=conference, name="instructions")
        path = conference_file_path(cf, "file.very-long-extension")
        ext = path.split(".")[-1]
        assert len(ext) < 10

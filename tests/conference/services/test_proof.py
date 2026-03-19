from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import EmailMessage
from django.utils import timezone
from faker.proxy import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    Paper,
    PaperAuthor,
    PaperProof,
    PaperState,
    Profile,
    Track,
)
from app.conference.services.proof import (
    ProofEligibilityError,
    ProofNotifyEmailContext,
    ProofService,
    RecipientDerivationError,
    SendProofNotifyStatus,
)
from app.core.models import User
from app.utils.email import EmailTemplate
from app.utils.files import FileTooLargeError
from tests.helpers import approx_now, update_object


@pytest.fixture
def paper(
    faker: Faker,
    user: User,
    conference: Conference,
    track: Track,
) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code=faker.lexify(text="????-###"),
        state=PaperState.ACCEPTED,
        announce_time=timezone.now(),
    )


@pytest.fixture
def proof(paper: Paper) -> PaperProof:
    return PaperProof.objects.create(
        paper=paper,
        recipient_name="Alice Smith",
        recipient_email="alice@example.com",
    )


def _add_corresponding_author(paper: Paper) -> PaperAuthor:
    return PaperAuthor.objects.create(
        paper=paper,
        ordering=0,
        given_name="Alice",
        family_name="Smith",
        email="alice@example.com",
        corresponding=True,
    )


@pytest.mark.django_db
class TestProofServiceUpsert:
    def test_creates_proof_from_corresponding_author(self, paper: Paper) -> None:
        _add_corresponding_author(paper)

        proof = ProofService.upsert(paper)

        assert proof.paper == paper
        assert proof.recipient_name == "Alice Smith"
        assert proof.recipient_email == "alice@example.com"
        assert PaperProof.objects.filter(paper=paper).exists()

    def test_picks_first_corresponding_by_ordering(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=1,
            given_name="Bob",
            family_name="Jones",
            email="bob@example.com",
            corresponding=True,
        )
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
            corresponding=True,
        )

        proof = ProofService.upsert(paper)

        assert proof.recipient_name == "Alice Smith"
        assert proof.recipient_email == "alice@example.com"

    def test_falls_back_to_owner_profile(self, paper: Paper) -> None:
        Profile.objects.create(
            user=paper.owner,
            given_name="Owner",
            family_name="Name",
        )
        update_object(paper.owner, email="owner@example.com")

        proof = ProofService.upsert(paper)

        assert proof.recipient_name == "Owner Name"
        assert proof.recipient_email == "owner@example.com"

    def test_ignores_non_corresponding_authors(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
            corresponding=False,
        )
        update_object(paper.owner, email="owner@example.com")

        with pytest.raises(RecipientDerivationError) as exc_info:
            ProofService.upsert(paper)

        assert "recipient_name" in exc_info.value.missing_fields

    def test_explicit_overrides(self, paper: Paper) -> None:
        _add_corresponding_author(paper)

        proof = ProofService.upsert(
            paper,
            recipient_name="Custom Name",
            recipient_email="custom@example.com",
        )

        assert proof.recipient_name == "Custom Name"
        assert proof.recipient_email == "custom@example.com"

    def test_partial_override_merges_with_derived(self, paper: Paper) -> None:
        _add_corresponding_author(paper)

        proof = ProofService.upsert(paper, recipient_name="Custom Name")

        assert proof.recipient_name == "Custom Name"
        assert proof.recipient_email == "alice@example.com"

    def test_updates_existing_proof(self, paper: Paper) -> None:
        _add_corresponding_author(paper)
        original = ProofService.upsert(paper)

        updated = ProofService.upsert(
            paper,
            recipient_name="New Name",
            recipient_email="new@example.com",
        )

        assert updated.pk == original.pk
        assert updated.recipient_name == "New Name"
        assert updated.recipient_email == "new@example.com"
        assert updated.paper == paper

    def test_accepted_revision_needed_eligible(self, paper: Paper) -> None:
        update_object(paper, state=PaperState.ACCEPTED_REVISION_NEEDED)

        proof = ProofService.upsert(
            paper,
            recipient_name="Alice",
            recipient_email="alice@example.com",
        )

        assert proof.paper == paper

    @pytest.mark.parametrize(
        "state",
        [PaperState.DRAFT, PaperState.SUBMITTED, PaperState.UNDER_REVIEW],
    )
    def test_rejects_non_decided_state(self, paper: Paper, state: PaperState) -> None:
        update_object(paper, state=state, announce_time=None)

        with pytest.raises(ProofEligibilityError):
            ProofService.upsert(
                paper,
                recipient_name="Alice",
                recipient_email="alice@example.com",
            )

        assert not PaperProof.objects.filter(paper=paper).exists()

    def test_rejects_rejected_state(self, paper: Paper) -> None:
        update_object(paper, state=PaperState.REJECTED)

        with pytest.raises(ProofEligibilityError):
            ProofService.upsert(
                paper,
                recipient_name="Alice",
                recipient_email="alice@example.com",
            )

    def test_rejects_unannounced(self, paper: Paper) -> None:
        update_object(paper, announce_time=None)

        with pytest.raises(ProofEligibilityError, match="not been announced"):
            ProofService.upsert(
                paper,
                recipient_name="Alice",
                recipient_email="alice@example.com",
            )

    def test_rejects_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(ProofEligibilityError, match="withdrawn"):
            ProofService.upsert(
                paper,
                recipient_name="Alice",
                recipient_email="alice@example.com",
            )

    def test_rejects_deleted(self, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(ProofEligibilityError, match="deleted"):
            ProofService.upsert(
                paper,
                recipient_name="Alice",
                recipient_email="alice@example.com",
            )

    def test_derivation_failure_reports_missing_fields(self, paper: Paper) -> None:
        update_object(paper.owner, email="")

        with pytest.raises(RecipientDerivationError) as exc_info:
            ProofService.upsert(paper)

        assert "recipient_name" in exc_info.value.missing_fields
        assert "recipient_email" in exc_info.value.missing_fields
        assert not PaperProof.objects.filter(paper=paper).exists()


@pytest.mark.django_db
class TestProofServiceUpload:
    @pytest.fixture(autouse=True)
    def mock_validate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.conference.services.proof.validate_upload")

    def test_uploads_file(self, proof: PaperProof) -> None:
        file = SimpleUploadedFile("proof.pdf", b"pdf content")

        result = ProofService.upload(proof, file)

        assert bool(result.file)
        assert Path(result.file.path).read_bytes() == b"pdf content"

    def test_first_upload_does_not_reset_confirmation(
        self,
        proof: PaperProof,
    ) -> None:
        update_object(
            proof,
            confirmed_time=proof.create_time,
            comment="looks good",
            comment_time=proof.create_time,
        )
        file = SimpleUploadedFile("proof.pdf", b"pdf content")

        result = ProofService.upload(proof, file)

        assert result.confirmed_time is not None
        assert result.comment == "looks good"
        assert result.comment_time is not None

    def test_reupload_resets_confirmation(self, proof: PaperProof) -> None:
        first_file = SimpleUploadedFile("proof.pdf", b"first")
        ProofService.upload(proof, first_file)
        update_object(
            proof,
            confirmed_time=proof.create_time,
            comment="looks good",
            comment_time=proof.create_time,
        )

        second_file = SimpleUploadedFile("proof.pdf", b"second")
        result = ProofService.upload(proof, second_file)

        assert result.confirmed_time is None
        assert result.comment == ""
        assert result.comment_time is None

    def test_calls_validate_upload(
        self,
        proof: PaperProof,
        mock_validate: MagicMock,
    ) -> None:
        file = SimpleUploadedFile("proof.pdf", b"content")
        allowed = {"application/pdf": [".pdf"]}

        ProofService.upload(proof, file, max_size=1000, allowed_types=allowed)

        mock_validate.assert_called_once_with(
            file,
            max_size=1000,
            allowed_types=allowed,
        )

    def test_validation_error_prevents_upload(
        self,
        proof: PaperProof,
        mock_validate: MagicMock,
    ) -> None:
        mock_validate.side_effect = FileTooLargeError("Too large")
        file = SimpleUploadedFile("proof.pdf", b"content")

        with pytest.raises(FileTooLargeError):
            ProofService.upload(proof, file)

        assert not bool(proof.file)

    def test_cleans_up_file_on_save_error(
        self,
        mocker: MockerFixture,
        proof: PaperProof,
        media_root: Path,
    ) -> None:
        mocker.patch.object(
            PaperProof,
            "save",
            side_effect=RuntimeError("DB error"),
        )
        file = SimpleUploadedFile("proof.pdf", b"content")

        with pytest.raises(RuntimeError, match="DB error"):
            ProofService.upload(proof, file)

        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(pdf_files) == 0


@pytest.mark.django_db
class TestProofServiceConfirm:
    def test_sets_confirmed_time(self, proof: PaperProof) -> None:
        assert proof.confirmed_time is None

        result = ProofService.confirm(proof)

        result.refresh_from_db()
        assert result.confirmed_time is not None

    def test_idempotent(self, proof: PaperProof) -> None:
        ProofService.confirm(proof)
        first_time = proof.confirmed_time

        ProofService.confirm(proof)
        proof.refresh_from_db()

        assert proof.confirmed_time == first_time


@pytest.mark.django_db
class TestProofServiceComment:
    def test_sets_comment_and_time(self, proof: PaperProof) -> None:
        result = ProofService.comment(proof, "page 3 has a broken formula")

        result.refresh_from_db()
        assert result.comment == "page 3 has a broken formula"
        assert result.comment_time is not None

    def test_upserts_comment(self, proof: PaperProof) -> None:
        ProofService.comment(proof, "first comment")
        first_time = proof.comment_time

        ProofService.comment(proof, "updated comment")
        proof.refresh_from_db()

        assert proof.comment == "updated comment"
        assert proof.comment_time >= first_time  # type: ignore[operator]


@pytest.fixture
def notify_template() -> EmailTemplate:
    return EmailTemplate(
        subject="Proof for {{ paper_code }}",
        body="Hello {{ recipient_name }}, review at {{ proof_url }}.",
    )


@pytest.fixture
def mock_send(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(EmailMessage, "send")


@pytest.fixture
def proof_with_file(paper: Paper) -> PaperProof:
    return PaperProof.objects.create(
        paper=paper,
        recipient_name="Alice Smith",
        recipient_email="alice@example.com",
        file=SimpleUploadedFile(
            "proof.pdf",
            b"%PDF-content",
            content_type="application/pdf",
        ),
    )


BASE_URL = "https://testserver/"


class TestProofNotifyEmailContextSample:
    def test_happy_path(self, settings: LazySettings) -> None:
        settings.SITE_NAME = "Test Site"

        context = ProofNotifyEmailContext.sample(base_url=BASE_URL)

        assert context.site_name == "Test Site"
        assert context.conference_name == "CONF-2025"
        assert context.paper_code == "PAPER-001"
        assert context.paper_title == "Sample Paper Title"
        assert context.recipient_name == "John Doe"
        assert "01000000000000000000000000" in str(context.proof_url)

    def test_renders_with_template(self, notify_template: EmailTemplate) -> None:
        context = ProofNotifyEmailContext.sample(base_url=BASE_URL)

        rendered = notify_template.render(context)

        assert "PAPER-001" in rendered.subject
        assert "John Doe" in rendered.body
        assert "paper-proofs/" in rendered.body


@pytest.mark.django_db(transaction=True)
class TestProofServiceSendNotification:
    def test_happy_path(
        self,
        proof_with_file: PaperProof,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        sent, recipient_email = ProofService.send_notification(
            proof_with_file.uid,
            template=notify_template,
            base_url=BASE_URL,
        )

        assert sent is True
        assert recipient_email == "alice@example.com"

        proof_with_file.refresh_from_db()
        assert proof_with_file.notification_time == approx_now()

        mock_send.assert_called_once()

    def test_skips_proof_without_file(
        self,
        proof: PaperProof,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        sent, recipient_email = ProofService.send_notification(
            proof.uid,
            template=notify_template,
            base_url=BASE_URL,
        )

        assert sent is False
        assert recipient_email == "alice@example.com"

        proof.refresh_from_db()
        assert proof.notification_time is None

        mock_send.assert_not_called()

    def test_raises_for_nonexistent_proof(
        self,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        with pytest.raises(PaperProof.DoesNotExist):
            ProofService.send_notification(
                ULID(),
                template=notify_template,
                base_url=BASE_URL,
            )

        mock_send.assert_not_called()

    def test_updates_notification_time_on_resend(
        self,
        proof_with_file: PaperProof,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        ProofService.send_notification(
            proof_with_file.uid,
            template=notify_template,
            base_url=BASE_URL,
        )
        proof_with_file.refresh_from_db()
        first_time = proof_with_file.notification_time

        ProofService.send_notification(
            proof_with_file.uid,
            template=notify_template,
            base_url=BASE_URL,
        )
        proof_with_file.refresh_from_db()

        assert proof_with_file.notification_time >= first_time  # type: ignore[operator]
        assert mock_send.call_count == 2

    def test_uses_database_transaction(
        self,
        mocker: MockerFixture,
        proof_with_file: PaperProof,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        mocker.patch.object(PaperProof, "save", side_effect=RuntimeError("DB error"))

        with pytest.raises(RuntimeError, match="DB error"):
            ProofService.send_notification(
                proof_with_file.uid,
                template=notify_template,
                base_url=BASE_URL,
            )

        proof_with_file.refresh_from_db()
        assert proof_with_file.notification_time is None

        mock_send.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestProofServiceSendNotifications:
    @pytest.fixture
    def proof_a(self, paper: Paper) -> PaperProof:
        return PaperProof.objects.create(
            paper=paper,
            recipient_name="Alice Smith",
            recipient_email="alice@example.com",
            file=SimpleUploadedFile("a.pdf", b"%PDF-a"),
        )

    @pytest.fixture
    def proof_b(
        self,
        faker: Faker,
        conference: Conference,
        track: Track,
    ) -> PaperProof:
        owner = User.objects.create_user(username=faker.user_name())
        other_paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=owner,
            code=faker.lexify(text="????-###"),
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        return PaperProof.objects.create(
            paper=other_paper,
            recipient_name="Bob Jones",
            recipient_email="bob@example.com",
            file=SimpleUploadedFile("b.pdf", b"%PDF-b"),
        )

    def test_happy_path(
        self,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
        proof_a: PaperProof,
        proof_b: PaperProof,
    ) -> None:
        results = ProofService.send_notifications(
            [proof_a.uid, proof_b.uid],
            template=notify_template,
            base_url=BASE_URL,
        )

        [result_a, result_b] = results
        assert result_a.proof == proof_a.uid
        assert result_a.status == SendProofNotifyStatus.SENT
        assert result_a.recipient_email == "alice@example.com"
        assert result_b.proof == proof_b.uid
        assert result_b.status == SendProofNotifyStatus.SENT
        assert result_b.recipient_email == "bob@example.com"

        assert mock_send.call_count == 2

    def test_empty_list(
        self,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        results = ProofService.send_notifications(
            [],
            template=notify_template,
            base_url=BASE_URL,
        )

        assert results == []
        mock_send.assert_not_called()

    def test_not_found_proof(
        self,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
        proof_a: PaperProof,
    ) -> None:
        nonexistent_uid = ULID()

        results = ProofService.send_notifications(
            [proof_a.uid, nonexistent_uid],
            template=notify_template,
            base_url=BASE_URL,
        )

        [result_a, result_missing] = results
        assert result_a.status == SendProofNotifyStatus.SENT
        assert result_missing.proof == nonexistent_uid
        assert result_missing.status == SendProofNotifyStatus.NOT_FOUND
        assert result_missing.reason is not None

        mock_send.assert_called_once()

    @pytest.fixture
    def proof_no_file(
        self,
        faker: Faker,
        conference: Conference,
        track: Track,
    ) -> PaperProof:
        owner = User.objects.create_user(username=faker.user_name())
        p = Paper.objects.create(
            conference=conference,
            track=track,
            owner=owner,
            code=faker.lexify(text="????-###"),
            state=PaperState.ACCEPTED,
            announce_time=timezone.now(),
        )
        return PaperProof.objects.create(
            paper=p,
            recipient_name="Carol Lee",
            recipient_email="carol@example.com",
        )

    def test_skipped_proof_without_file(
        self,
        notify_template: EmailTemplate,
        mock_send: MagicMock,
        proof_a: PaperProof,
        proof_no_file: PaperProof,
    ) -> None:
        results = ProofService.send_notifications(
            [proof_a.uid, proof_no_file.uid],
            template=notify_template,
            base_url=BASE_URL,
        )

        [result_a, result_no_file] = results
        assert result_a.status == SendProofNotifyStatus.SENT
        assert result_no_file.proof == proof_no_file.uid
        assert result_no_file.status == SendProofNotifyStatus.SKIPPED
        assert result_no_file.recipient_email == "carol@example.com"
        assert result_no_file.reason is not None

        mock_send.assert_called_once()

    def test_failure_does_not_affect_others(
        self,
        mocker: MockerFixture,
        notify_template: EmailTemplate,
        proof_a: PaperProof,
        proof_b: PaperProof,
    ) -> None:
        mock = mocker.patch.object(EmailMessage, "send")
        mock.side_effect = [None, RuntimeError("SMTP error")]

        results = ProofService.send_notifications(
            [proof_a.uid, proof_b.uid],
            template=notify_template,
            base_url=BASE_URL,
        )

        [result_a, result_b] = results
        assert result_a.status == SendProofNotifyStatus.SENT
        assert result_b.status == SendProofNotifyStatus.FAILED
        assert result_b.reason is not None

        assert mock.call_count == 2

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from faker.proxy import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    Paper,
    PaperFinal,
    PaperState,
    PaperSubmission,
    Track,
)
from app.conference.services import RevisionService
from app.core.models import User
from app.utils.files import FileTooLargeError
from tests.helpers import update_object


@pytest.fixture
def paper(user: User, conference: Conference, track: Track) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
    )


@pytest.mark.django_db
class TestRevisionServiceNextRevision:
    def test_returns_one_when_no_submissions_exist(self, paper: Paper) -> None:
        revision = RevisionService.next_revision(PaperSubmission, paper)

        assert revision == 1

    def test_returns_one_when_no_finals_exist(self, paper: Paper) -> None:
        revision = RevisionService.next_revision(PaperFinal, paper)

        assert revision == 1

    def test_returns_next_revision_for_submissions(self, paper: Paper) -> None:
        PaperSubmission.objects.create(paper=paper, revision=1, file="test1.pdf")
        PaperSubmission.objects.create(paper=paper, revision=2, file="test2.pdf")

        revision = RevisionService.next_revision(PaperSubmission, paper)

        assert revision == 3

    def test_returns_next_revision_for_finals(self, paper: Paper) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="test1.pdf")
        PaperFinal.objects.create(paper=paper, revision=3, source_file="test3.pdf")

        revision = RevisionService.next_revision(PaperFinal, paper)

        assert revision == 4

    def test_ignores_revisions_from_other_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        other_paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-002",
        )
        PaperSubmission.objects.create(paper=other_paper, revision=5, file="other.pdf")

        revision = RevisionService.next_revision(PaperSubmission, paper)

        assert revision == 1


@pytest.mark.django_db(transaction=True)
class TestRevisionServiceDeleteRevision:
    def test_raises_when_called_outside_transaction(self, paper: Paper) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="test.pdf",
        )

        with pytest.raises(RuntimeError, match="must be called within a transaction"):
            RevisionService.delete_revision(submission)

    def test_deletes_submission_record(self, paper: Paper) -> None:
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="test.pdf",
        )

        with transaction.atomic():
            RevisionService.delete_revision(submission)

        assert not PaperSubmission.objects.filter(pk=submission.pk).exists()

    def test_deletes_final_record(self, paper: Paper) -> None:
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.pdf",
        )

        with transaction.atomic():
            RevisionService.delete_revision(final)

        assert not PaperFinal.objects.filter(pk=final.pk).exists()

    def test_schedules_submission_file_deletion_on_commit(
        self,
        mocker: MagicMock,
        paper: Paper,
    ) -> None:
        mock_unlink = mocker.patch("app.conference.services.revision.unlink_safe")
        submission = PaperSubmission.objects.create(
            paper=paper,
            revision=1,
            file="test.pdf",
        )
        file_path = Path(submission.file.path)

        with transaction.atomic():
            RevisionService.delete_revision(submission)
            mock_unlink.assert_not_called()

        mock_unlink.assert_called_once_with(file_path)

    def test_schedules_final_source_file_deletion_on_commit(
        self,
        mocker: MagicMock,
        paper: Paper,
    ) -> None:
        mock_unlink = mocker.patch("app.conference.services.revision.unlink_safe")
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.pdf",
        )
        source_path = Path(final.source_file.path)

        with transaction.atomic():
            RevisionService.delete_revision(final)

        mock_unlink.assert_called_once_with(source_path)

    def test_schedules_both_final_files_deletion_on_commit(
        self,
        mocker: MagicMock,
        paper: Paper,
    ) -> None:
        mock_unlink = mocker.patch("app.conference.services.revision.unlink_safe")
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.pdf",
            viewable_file="viewable.pdf",
        )
        source_path = Path(final.source_file.path)
        viewable_path = Path(final.viewable_file.path)

        with transaction.atomic():
            RevisionService.delete_revision(final)

        assert mock_unlink.call_count == 2
        mock_unlink.assert_any_call(source_path)
        mock_unlink.assert_any_call(viewable_path)


@pytest.mark.django_db(transaction=True)
class TestRevisionServiceDeleteRevisionE2E:
    def test_deletes_file_on_commit(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        submission.file.save("test.pdf", ContentFile(b"test content"))
        file_path = Path(submission.file.path)
        assert file_path.exists()

        with transaction.atomic():
            RevisionService.delete_revision(submission)
            assert file_path.exists()

        assert not file_path.exists()

    def test_preserves_file_on_rollback(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        submission.file.save("test.pdf", ContentFile(b"test content"))
        file_path = Path(submission.file.path)
        assert file_path.exists()

        with pytest.raises(ValueError, match="forced rollback"), transaction.atomic():
            RevisionService.delete_revision(submission)
            raise ValueError("forced rollback")

        assert file_path.exists()

    def test_deletes_both_final_files_on_commit(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        final.source_file.save("source.pdf", ContentFile(b"source"))
        final.viewable_file.save("viewable.pdf", ContentFile(b"viewable"))
        source_path = Path(final.source_file.path)
        viewable_path = Path(final.viewable_file.path)
        assert source_path.exists()
        assert viewable_path.exists()

        with transaction.atomic():
            RevisionService.delete_revision(final)

        assert not source_path.exists()
        assert not viewable_path.exists()

    def test_preserves_both_final_files_on_rollback(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        final.source_file.save("source.pdf", ContentFile(b"source"))
        final.viewable_file.save("viewable.pdf", ContentFile(b"viewable"))
        source_path = Path(final.source_file.path)
        viewable_path = Path(final.viewable_file.path)

        with pytest.raises(ValueError, match="forced rollback"), transaction.atomic():
            RevisionService.delete_revision(final)
            raise ValueError("forced rollback")

        assert source_path.exists()
        assert viewable_path.exists()

    def test_logs_and_continues_on_unlink_error(
        self,
        mocker: MagicMock,
        paper: Paper,
    ) -> None:
        mock_logger = mocker.patch("app.conference.services.revision.logger")
        submission = PaperSubmission(paper=paper, revision=1)
        submission.file.save("test.pdf", ContentFile(b"test content"))
        file_path = Path(submission.file.path)
        mocker.patch.object(
            Path,
            "unlink",
            side_effect=PermissionError("Access denied"),
        )

        with transaction.atomic():
            RevisionService.delete_revision(submission)

        assert not PaperSubmission.objects.filter(pk=submission.pk).exists()

        mock_logger.exception.assert_called_once()
        assert "Failed to delete" in mock_logger.exception.call_args[0][0]
        assert mock_logger.exception.call_args[1]["path"] == file_path


@pytest.mark.django_db(transaction=True)
class TestRevisionServiceCreateSubmission:
    @pytest.fixture(autouse=True)
    def mock_validate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.conference.services.revision.validate_upload")

    def test_creates_submission_with_revision_one(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")

        submission = RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
        )

        db_submission = PaperSubmission.objects.get(pk=submission.pk)
        assert db_submission.paper == submission.paper == paper
        assert db_submission.revision == submission.revision == 1
        assert db_submission.uploader == submission.uploader == user

    def test_increments_revision_number(self, paper: Paper, user: User) -> None:
        PaperSubmission.objects.create(paper=paper, revision=1, file="old.pdf")
        file = SimpleUploadedFile("test.pdf", b"content")

        submission = RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
        )

        assert submission.revision == 2

    def test_saves_file_to_disk(self, paper: Paper, user: User) -> None:
        file = SimpleUploadedFile("test.pdf", b"file content")

        submission = RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
        )

        assert Path(submission.file.path).exists()
        assert Path(submission.file.path).read_bytes() == b"file content"

    def test_calls_validate_upload_with_parameters(
        self,
        paper: Paper,
        user: User,
        mock_validate: MagicMock,
    ) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")
        allowed_types = {"application/pdf": [".pdf"]}

        RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
            max_size=1000,
            allowed_types=allowed_types,
        )

        mock_validate.assert_called_once_with(
            file,
            max_size=1000,
            allowed_types=allowed_types,
        )

    def test_raises_validation_error_before_creating_record(
        self,
        paper: Paper,
        user: User,
        mock_validate: MagicMock,
    ) -> None:
        mock_validate.side_effect = FileTooLargeError("Too large")
        file = SimpleUploadedFile("test.pdf", b"content")

        with pytest.raises(FileTooLargeError):
            RevisionService.create_submission(paper=paper, file=file, uploader=user)

        assert not paper.submissions.exists()

    def test_cleans_up_file_on_pre_save_error(
        self,
        mocker: MagicMock,
        paper: Paper,
        user: User,
        media_root: Path,
    ) -> None:
        mocker.patch.object(
            RevisionService,
            "next_revision",
            side_effect=RuntimeError("Unknown error"),
        )
        file = SimpleUploadedFile("test.pdf", b"content")

        with pytest.raises(RuntimeError, match="Unknown error"):
            RevisionService.create_submission(paper=paper, file=file, uploader=user)

        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(pdf_files) == 0

    def test_cleans_up_file_on_database_error(
        self,
        mocker: MagicMock,
        paper: Paper,
        user: User,
        media_root: Path,
    ) -> None:
        mocker.patch.object(
            PaperSubmission,
            "save",
            side_effect=RuntimeError("DB error"),
        )
        file = SimpleUploadedFile("test.pdf", b"content")

        with pytest.raises(RuntimeError, match="DB error"):
            RevisionService.create_submission(paper=paper, file=file, uploader=user)

        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(pdf_files) == 0

    @pytest.mark.parametrize("state", [PaperState.DRAFT, PaperState.SUBMITTED])
    def test_deletes_oldest_revision_in_editable_state(
        self,
        paper: Paper,
        user: User,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)

        old = PaperSubmission(paper=paper, revision=1, uploader=user)
        old.file.save("old.pdf", ContentFile(b"old"))
        old_path = Path(old.file.path)

        file = SimpleUploadedFile("new.pdf", b"new content")
        new = RevisionService.create_submission(paper=paper, file=file, uploader=user)

        assert not PaperSubmission.objects.filter(pk=old.pk).exists()
        assert PaperSubmission.objects.filter(pk=new.pk).exists()
        assert not old_path.exists()

    @pytest.mark.parametrize(
        "state",
        [
            PaperState.UNDER_REVIEW,
            PaperState.REJECTED,
            PaperState.ACCEPTED,
            PaperState.ACCEPTED_REVISION_NEEDED,
        ],
    )
    def test_does_not_delete_revisions_in_non_editable_state(
        self,
        paper: Paper,
        user: User,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)

        old = PaperSubmission(paper=paper, revision=1, uploader=user)
        old.file.save("old.pdf", ContentFile(b"old"))

        file = SimpleUploadedFile("new.pdf", b"new content")
        RevisionService.create_submission(paper=paper, file=file, uploader=user)

        assert paper.submissions.count() == 2

    def test_does_not_delete_revisions_uploaded_by_others(
        self,
        faker: Faker,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, state=PaperState.DRAFT)

        other_user = User.objects.create_user(username=faker.user_name())
        other_submission = PaperSubmission(paper=paper, revision=1, uploader=other_user)
        other_submission.file.save("other.pdf", ContentFile(b"other"))

        file = SimpleUploadedFile("new.pdf", b"new content")
        RevisionService.create_submission(paper=paper, file=file, uploader=user)

        assert PaperSubmission.objects.filter(pk=other_submission.pk).exists()
        assert paper.submissions.count() == 2

    def test_skip_cleanup_preserves_all_revisions(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, state=PaperState.DRAFT)

        old = PaperSubmission(paper=paper, revision=1, uploader=user)
        old.file.save("old.pdf", ContentFile(b"old"))

        file = SimpleUploadedFile("new.pdf", b"new content")
        RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
            skip_cleanup=True,
        )

        assert paper.submissions.count() == 2

    def test_deletes_only_oldest_when_multiple_exist(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, state=PaperState.DRAFT)

        rev1 = PaperSubmission(paper=paper, revision=1, uploader=user)
        rev1.file.save("rev1.pdf", ContentFile(b"rev1"))
        rev2 = PaperSubmission(paper=paper, revision=2, uploader=user)
        rev2.file.save("rev2.pdf", ContentFile(b"rev2"))

        file = SimpleUploadedFile("new.pdf", b"new content")
        RevisionService.create_submission(paper=paper, file=file, uploader=user)

        assert not PaperSubmission.objects.filter(pk=rev1.pk).exists()
        assert PaperSubmission.objects.filter(pk=rev2.pk).exists()
        assert paper.submissions.count() == 2

    def test_no_cleanup_when_only_one_revision_exists(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, state=PaperState.DRAFT)

        file = SimpleUploadedFile("new.pdf", b"new content")
        submission = RevisionService.create_submission(
            paper=paper,
            file=file,
            uploader=user,
        )

        assert PaperSubmission.objects.filter(pk=submission.pk).exists()
        assert paper.submissions.count() == 1

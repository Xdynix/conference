from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.db import transaction

from app.conference.models import (
    Conference,
    Paper,
    PaperFinal,
    PaperSubmission,
    Track,
)
from app.conference.services.revision import RevisionService
from app.core.models import User


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
    @pytest.fixture(autouse=True)
    def media_root(self, tmp_path: Path, settings: LazySettings) -> Path:
        settings.MEDIA_ROOT = tmp_path
        return tmp_path

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

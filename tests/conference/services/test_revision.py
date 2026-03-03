import hashlib
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
from app.conference.services.revision import FinalRevisionLimitError
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
class TestRevisionFileCleanup:
    def test_deletes_file_on_commit(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        submission.file.save("test.pdf", ContentFile(b"test content"))
        file_path = Path(submission.file.path)
        assert file_path.exists()

        with transaction.atomic():
            submission.delete()
            assert file_path.exists()

        assert not file_path.exists()

    def test_preserves_file_on_rollback(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        submission.file.save("test.pdf", ContentFile(b"test content"))
        file_path = Path(submission.file.path)
        assert file_path.exists()

        with pytest.raises(ValueError, match="forced rollback"), transaction.atomic():
            submission.delete()
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
            final.delete()

        assert not source_path.exists()
        assert not viewable_path.exists()

    def test_preserves_both_final_files_on_rollback(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        final.source_file.save("source.pdf", ContentFile(b"source"))
        final.viewable_file.save("viewable.pdf", ContentFile(b"viewable"))
        source_path = Path(final.source_file.path)
        viewable_path = Path(final.viewable_file.path)

        with pytest.raises(ValueError, match="forced rollback"), transaction.atomic():
            final.delete()
            raise ValueError("forced rollback")

        assert source_path.exists()
        assert viewable_path.exists()


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
        assert db_submission.sha256 == hashlib.sha256(b"content").hexdigest()

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


@pytest.mark.django_db(transaction=True)
class TestRevisionServiceCreateFinal:
    @pytest.fixture(autouse=True)
    def mock_validate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.conference.services.revision.validate_upload")

    def test_creates_final_with_revision_one(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        source_file = SimpleUploadedFile("source.zip", b"source content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=False,
        )

        db_final = PaperFinal.objects.get(pk=final.pk)
        assert db_final.paper == final.paper == paper
        assert db_final.revision == final.revision == 1
        assert db_final.uploader == final.uploader == user
        assert db_final.source_sha256 == hashlib.sha256(b"source content").hexdigest()
        assert db_final.viewable_sha256 == ""

    def test_increments_revision_number(self, paper: Paper, user: User) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="old.zip")
        source_file = SimpleUploadedFile("source.zip", b"content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=False,
        )

        assert final.revision == 2

    def test_saves_source_file_to_disk(self, paper: Paper, user: User) -> None:
        source_file = SimpleUploadedFile("source.zip", b"source content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=False,
        )

        assert Path(final.source_file.path).exists()
        assert Path(final.source_file.path).read_bytes() == b"source content"

    def test_saves_viewable_file_when_provided(self, paper: Paper, user: User) -> None:
        source_file = SimpleUploadedFile("source.zip", b"source")
        viewable_file = SimpleUploadedFile("viewable.pdf", b"viewable content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=viewable_file,
            uploader=user,
            enforce_limit=False,
        )

        assert Path(final.source_file.path).exists()
        assert Path(final.viewable_file.path).exists()
        assert Path(final.viewable_file.path).read_bytes() == b"viewable content"
        assert final.source_sha256 == hashlib.sha256(b"source").hexdigest()
        assert final.viewable_sha256 == hashlib.sha256(b"viewable content").hexdigest()

    def test_calls_validate_upload_for_source_file(
        self,
        paper: Paper,
        user: User,
        mock_validate: MagicMock,
    ) -> None:
        source_file = SimpleUploadedFile("source.zip", b"content")
        source_allowed_types = {"application/zip": [".zip"]}

        RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=False,
            source_max_size=1000,
            source_allowed_types=source_allowed_types,
        )

        mock_validate.assert_called_once_with(
            source_file,
            max_size=1000,
            allowed_types=source_allowed_types,
        )

    def test_calls_validate_upload_for_both_files(
        self,
        paper: Paper,
        user: User,
        mock_validate: MagicMock,
    ) -> None:
        source_file = SimpleUploadedFile("source.zip", b"source")
        viewable_file = SimpleUploadedFile("viewable.pdf", b"viewable")
        source_allowed_types = {"application/zip": [".zip"]}
        viewable_allowed_types = {"application/pdf": [".pdf"]}

        RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=viewable_file,
            uploader=user,
            enforce_limit=False,
            source_max_size=1000,
            source_allowed_types=source_allowed_types,
            viewable_max_size=500,
            viewable_allowed_types=viewable_allowed_types,
        )

        assert mock_validate.call_count == 2
        mock_validate.assert_any_call(
            source_file,
            max_size=1000,
            allowed_types=source_allowed_types,
        )
        mock_validate.assert_any_call(
            viewable_file,
            max_size=500,
            allowed_types=viewable_allowed_types,
        )

    def test_raises_validation_error_before_creating_record(
        self,
        paper: Paper,
        user: User,
        mock_validate: MagicMock,
    ) -> None:
        mock_validate.side_effect = FileTooLargeError("Too large")
        source_file = SimpleUploadedFile("source.zip", b"content")

        with pytest.raises(FileTooLargeError):
            RevisionService.create_final(
                paper=paper,
                source_file=source_file,
                viewable_file=None,
                uploader=user,
                enforce_limit=False,
            )

        assert not paper.finals.exists()

    def test_cleans_up_source_file_on_database_error(
        self,
        mocker: MagicMock,
        paper: Paper,
        user: User,
        media_root: Path,
    ) -> None:
        mocker.patch.object(
            PaperFinal,
            "save",
            side_effect=RuntimeError("DB error"),
        )
        source_file = SimpleUploadedFile("source.zip", b"content")

        with pytest.raises(RuntimeError, match="DB error"):
            RevisionService.create_final(
                paper=paper,
                source_file=source_file,
                viewable_file=None,
                uploader=user,
                enforce_limit=False,
            )

        zip_files = list(media_root.rglob("*.zip"))
        assert len(zip_files) == 0

    def test_cleans_up_both_files_on_database_error(
        self,
        mocker: MagicMock,
        paper: Paper,
        user: User,
        media_root: Path,
    ) -> None:
        mocker.patch.object(
            PaperFinal,
            "save",
            side_effect=RuntimeError("DB error"),
        )
        source_file = SimpleUploadedFile("source.zip", b"source")
        viewable_file = SimpleUploadedFile("viewable.pdf", b"viewable")

        with pytest.raises(RuntimeError, match="DB error"):
            RevisionService.create_final(
                paper=paper,
                source_file=source_file,
                viewable_file=viewable_file,
                uploader=user,
                enforce_limit=False,
            )

        zip_files = list(media_root.rglob("*.zip"))
        pdf_files = list(media_root.rglob("*.pdf"))
        assert len(zip_files) == 0
        assert len(pdf_files) == 0

    def test_enforces_limit_when_enabled(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, final_revision_limit=1)
        PaperFinal.objects.create(paper=paper, revision=1, source_file="existing.zip")

        source_file = SimpleUploadedFile("new.zip", b"content")

        with pytest.raises(FinalRevisionLimitError):
            RevisionService.create_final(
                paper=paper,
                source_file=source_file,
                viewable_file=None,
                uploader=user,
                enforce_limit=True,
            )

        assert paper.finals.count() == 1

    def test_bypasses_limit_when_disabled(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, final_revision_limit=1)
        PaperFinal.objects.create(paper=paper, revision=1, source_file="existing.zip")

        source_file = SimpleUploadedFile("new.zip", b"content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=False,
        )

        assert paper.finals.count() == 2
        assert final.revision == 2

    def test_allows_upload_when_under_limit(
        self,
        paper: Paper,
        user: User,
    ) -> None:
        update_object(paper, final_revision_limit=2)
        PaperFinal.objects.create(paper=paper, revision=1, source_file="existing.zip")

        source_file = SimpleUploadedFile("new.zip", b"content")

        final = RevisionService.create_final(
            paper=paper,
            source_file=source_file,
            viewable_file=None,
            uploader=user,
            enforce_limit=True,
        )

        assert paper.finals.count() == 2
        assert final.revision == 2

    def test_limit_check_does_not_clean_up_file_on_error(
        self,
        paper: Paper,
        user: User,
        media_root: Path,
    ) -> None:
        update_object(paper, final_revision_limit=1)
        PaperFinal.objects.create(paper=paper, revision=1, source_file="existing.zip")

        source_file = SimpleUploadedFile("new.zip", b"content")

        with pytest.raises(FinalRevisionLimitError):
            RevisionService.create_final(
                paper=paper,
                source_file=source_file,
                viewable_file=None,
                uploader=user,
                enforce_limit=True,
            )

        zip_files = list(media_root.rglob("new.zip"))
        assert len(zip_files) == 0

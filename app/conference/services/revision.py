from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path

from django.core.files.uploadedfile import UploadedFile
from django.db import connection, transaction
from django.db.models import Max
from loguru import logger

from app.conference.models import Paper, PaperFinal, PaperState, PaperSubmission
from app.core.models import User
from app.infra.models import Mutex
from app.utils.files import validate_upload


class FinalRevisionLimitError(Exception):
    pass


def unlink_safe(path: Path) -> None:
    """Delete a file, logging errors instead of raising."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete revision file.", path=path)


class RevisionService:
    @classmethod
    def next_revision(
        cls,
        model_class: type[PaperSubmission] | type[PaperFinal],
        paper: Paper,
    ) -> int:
        """Calculate next revision number for a paper.

        Must be called within a ``Mutex`` lock to prevent race conditions.
        """
        max_revision = (
            model_class.objects.filter(paper=paper).aggregate(
                max_revision=Max("revision")
            )
        )["max_revision"]
        return (max_revision or 0) + 1

    @classmethod
    def delete_revision(cls, revision: PaperSubmission | PaperFinal) -> None:
        """Delete a revision record and schedule its file(s) for removal on commit.

        Must be called within a transaction. Files are deleted after the transaction
        commits to avoid orphaned records if the transaction rolls back.
        """
        if not connection.in_atomic_block:
            raise RuntimeError("`delete_revision` must be called within a transaction.")

        file_paths: list[Path] = []

        if isinstance(revision, PaperSubmission):
            file_paths.append(Path(revision.file.path))
        else:
            file_paths.append(Path(revision.source_file.path))
            if revision.viewable_file:
                file_paths.append(Path(revision.viewable_file.path))

        revision.delete()

        for path in file_paths:
            transaction.on_commit(partial(unlink_safe, path))

    @classmethod
    def create_submission(
        cls,
        *,
        paper: Paper,
        file: UploadedFile,
        uploader: User,
        skip_cleanup: bool = False,
        max_size: int = 0,
        allowed_types: Mapping[str, Sequence[str]] | None = None,
    ) -> PaperSubmission:
        """Upload a submission file for a paper.

        Creates a new revision of the paper submission. For author uploads (when
        ``skip_cleanup`` is False), cleans up the oldest revision by the same uploader
        if there's more than one, but only when the paper is in Draft or Submitted
        state.

        Args:
            paper: The paper to upload the submission for.
            file: The uploaded file.
            uploader: The user uploading the file.
            skip_cleanup: If ``True``, skips cleanup of old revisions (for admin
                uploads).
            max_size: Maximum allowed file size in bytes. Skipped if not positive.
            allowed_types: Mapping of allowed MIME types to their valid extensions.

        Raises:
            UploadValidationError: If file validation fails.
        """
        # Validate before acquiring lock to avoid holding it during validation.
        validate_upload(file, max_size=max_size, allowed_types=allowed_types)

        new_file_path: Path | None = None

        try:
            with Mutex.lock_in_transaction(
                str(paper.pk),
                namespace="paper_submissions",
            ):
                revision = cls.next_revision(PaperSubmission, paper)

                submission = PaperSubmission(
                    paper=paper,
                    revision=revision,
                    uploader=uploader,
                )
                submission.file.save(file.name, file, save=False)
                new_file_path = Path(submission.file.path)

                submission.save()

                # Cleanup: delete single oldest revision by this uploader when in
                # editable states. Admin uploads (skip_cleanup=True) preserve all.
                if not skip_cleanup and paper.state in (
                    PaperState.DRAFT,
                    PaperState.SUBMITTED,
                ):
                    oldest = (
                        PaperSubmission.objects.filter(paper=paper, uploader=uploader)
                        .exclude(pk=submission.pk)
                        .order_by("revision")
                        .first()
                    )
                    if oldest:
                        cls.delete_revision(oldest)

                return submission

        except Exception:
            if new_file_path:
                unlink_safe(new_file_path)
            raise

    @classmethod
    def create_final(
        cls,
        *,
        paper: Paper,
        source_file: UploadedFile,
        viewable_file: UploadedFile | None,
        uploader: User,
        enforce_limit: bool = True,
        source_max_size: int = 0,
        source_allowed_types: Mapping[str, Sequence[str]] | None = None,
        viewable_max_size: int = 0,
        viewable_allowed_types: Mapping[str, Sequence[str]] | None = None,
    ) -> PaperFinal:
        """Upload final version files for a paper.

        Creates a new revision of the paper final. All revisions are preserved (no
        cleanup).

        Args:
            paper: The paper to upload the final for.
            source_file: The source file (required).
            viewable_file: The viewable file (optional, typically PDF for viewing).
            uploader: The user uploading the files.
            enforce_limit: If ``True``, enforces ``paper.final_revision_limit``. Set to
                ``False`` for admin uploads that bypass the limit.
            source_max_size: Maximum allowed source file size in bytes.
            source_allowed_types: Mapping of allowed MIME types to extensions for
                source file.
            viewable_max_size: Maximum allowed viewable file size in bytes.
            viewable_allowed_types: Mapping of allowed MIME types to extensions for
                viewable file.

        Raises:
            FinalRevisionLimitError: If limit is enforced and quota is exceeded.
            UploadValidationError: If file validation fails.
        """
        # Validate before acquiring lock to avoid holding it during validation.
        validate_upload(
            source_file,
            max_size=source_max_size,
            allowed_types=source_allowed_types,
        )
        if viewable_file:
            validate_upload(
                viewable_file,
                max_size=viewable_max_size,
                allowed_types=viewable_allowed_types,
            )

        new_source_path: Path | None = None
        new_viewable_path: Path | None = None

        try:
            with Mutex.lock_in_transaction(str(paper.pk), namespace="paper_finals"):
                if enforce_limit:
                    # Avoid `paper.finals` because prefetched data can make counts
                    # stale.
                    current_count = PaperFinal.objects.filter(paper=paper).count()
                    if current_count >= paper.final_revision_limit:
                        raise FinalRevisionLimitError

                revision = cls.next_revision(PaperFinal, paper)

                final = PaperFinal(
                    paper=paper,
                    revision=revision,
                    uploader=uploader,
                )
                final.source_file.save(source_file.name, source_file, save=False)
                new_source_path = Path(final.source_file.path)
                if viewable_file:
                    final.viewable_file.save(
                        viewable_file.name,
                        viewable_file,
                        save=False,
                    )
                    new_viewable_path = Path(final.viewable_file.path)

                final.save()

                return final

        except Exception:
            if new_source_path:
                unlink_safe(new_source_path)
            if new_viewable_path:
                unlink_safe(new_viewable_path)
            raise


# TODO: Scan and clean up orphan files.

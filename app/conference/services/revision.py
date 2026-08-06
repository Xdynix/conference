from collections.abc import Mapping, Sequence

from django.core.files.uploadedfile import UploadedFile
from django.db.models import Max

from app.conference.models import Paper, PaperFinal, PaperState, PaperSubmission
from app.core.models import User
from app.infra.models import Mutex
from app.utils.files import compute_sha256, validate_upload


class FinalRevisionLimitError(Exception):
    pass


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
    def create_submission(
        cls,
        *,
        paper: Paper,
        file: UploadedFile[bytes],
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

        new_file_name: str | None = None

        try:
            with Mutex.lock_in_transaction(
                str(paper.pk),
                namespace="paper_submissions",
            ):
                revision = cls.next_revision(PaperSubmission, paper)

                submission = PaperSubmission(
                    paper=paper,
                    revision=revision,
                    sha256=compute_sha256(file),
                    uploader=uploader,
                )
                submission.file.save(file.name, file, save=False)  # type: ignore[arg-type]
                new_file_name = submission.file.name

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
                        oldest.delete()

                return submission

        except Exception:
            if new_file_name:
                submission.file.storage.delete(new_file_name)
            raise

    @classmethod
    def create_final(
        cls,
        *,
        paper: Paper,
        source_file: UploadedFile[bytes],
        viewable_file: UploadedFile[bytes] | None,
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

        new_source_name: str | None = None
        new_viewable_name: str | None = None

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
                    source_sha256=compute_sha256(source_file),
                    uploader=uploader,
                )
                final.source_file.save(source_file.name, source_file, save=False)  # type: ignore[arg-type]
                new_source_name = final.source_file.name
                if viewable_file:
                    final.viewable_sha256 = compute_sha256(viewable_file)
                    final.viewable_file.save(
                        viewable_file.name,  # type: ignore[arg-type]
                        viewable_file,
                        save=False,
                    )
                    new_viewable_name = final.viewable_file.name

                final.save()

                return final

        except Exception:
            if new_source_name:
                final.source_file.storage.delete(new_source_name)
            if new_viewable_name:
                final.viewable_file.storage.delete(new_viewable_name)
            raise


# TODO: Scan and clean up orphan files and empty directories.
#  django-cleanup handles file deletion on model delete and field replace,
#  but does not remove the directories left behind.

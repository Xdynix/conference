from functools import partial
from pathlib import Path

from django.db import connection, transaction
from django.db.models import Max
from loguru import logger

from app.conference.models import Paper, PaperFinal, PaperSubmission


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

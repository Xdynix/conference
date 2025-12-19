from collections.abc import Container
from functools import lru_cache

from django.conf import settings
from django.core.files.uploadedfile import TemporaryUploadedFile, UploadedFile
from django.utils.translation import gettext as _
from magika import Magika

# Max size for in-memory file type detection. Files larger than this should be
# `TemporaryUploadedFile` with a path. If an in-memory file exceeds this, something
# is wrong (e.g., large `SimpleUploadedFile` in tests).
MAX_MEMORY_DETECTION_SIZE = settings.FILE_UPLOAD_MAX_MEMORY_SIZE * 2


class UploadValidationError(Exception):
    pass


class FileTooLargeError(UploadValidationError):
    pass


class InvalidFileTypeError(UploadValidationError):
    pass


@lru_cache(maxsize=1)
def get_magika() -> Magika:
    """Lazy singleton for Magika instance."""
    return Magika()


def validate_upload(
    file: UploadedFile,
    *,
    max_size: int = 0,
    allowed_types: Container[str] = (),
) -> None:
    """Validate uploaded file size and MIME type.

    Args:
        file: The uploaded file to validate.
        max_size: Maximum allowed size in bytes. Skipped if not positive.
        allowed_types: Allowed MIME types. Skipped if empty.

    Raises:
        FileTooLargeError: If file exceeds size limit.
        InvalidFileTypeError: If file MIME type is not allowed.
        RuntimeError: If an in-memory file exceeds ``MAX_MEMORY_DETECTION_SIZE``.
            This indicates incorrect usage (e.g., large ``SimpleUploadedFile`` in
            tests). Large files should use ``TemporaryUploadedFile``.
    """
    if file.size is not None and 0 < max_size < file.size:
        raise FileTooLargeError(_("File size exceeds maximum allowed."))

    if allowed_types:
        magika = get_magika()

        if isinstance(file, TemporaryUploadedFile):
            result = magika.identify_path(file.temporary_file_path())
        else:
            original_pos = file.tell()
            file.seek(0)
            content = file.read(MAX_MEMORY_DETECTION_SIZE + 1)
            file.seek(original_pos)

            if len(content) > MAX_MEMORY_DETECTION_SIZE:
                raise RuntimeError(
                    "In-memory file too large for type detection: "
                    f">{MAX_MEMORY_DETECTION_SIZE} bytes. "
                    "Use TemporaryUploadedFile for large files."
                )

            result = magika.identify_bytes(content)

        if result.output.mime_type not in allowed_types:
            raise InvalidFileTypeError(_("File type not allowed."))

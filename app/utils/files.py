import sys
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from django.conf import settings
from django.core.files.uploadedfile import TemporaryUploadedFile, UploadedFile
from django.db.models.fields.files import FieldFile
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils.translation import gettext as _
from loguru import logger
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


class MissingFilenameError(UploadValidationError):
    pass


class ExtensionMismatchError(UploadValidationError):
    pass


@lru_cache(maxsize=1)
def get_magika() -> Magika:
    """Lazy singleton for Magika instance."""
    return Magika()


def validate_upload(
    file: UploadedFile,
    *,
    max_size: int = 0,
    allowed_types: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Validate uploaded file size, MIME type, and extension.

    Args:
        file: The uploaded file to validate.
        max_size: Maximum allowed size in bytes. Skipped if not positive.
        allowed_types: Mapping of allowed MIME types to their valid extensions. Skipped
            if ``None`` or empty.

    Raises:
        FileTooLargeError: If file exceeds size limit.
        MissingFilenameError: If file has no filename.
        InvalidFileTypeError: If file MIME type is not allowed.
        ExtensionMismatchError: If file extension does not match detected MIME type.
        RuntimeError: If an in-memory file exceeds ``MAX_MEMORY_DETECTION_SIZE``.
            This indicates incorrect usage (e.g., large ``SimpleUploadedFile`` in
            tests). Large files should use ``TemporaryUploadedFile``.
    """
    if file.size is not None and 0 < max_size < file.size:
        raise FileTooLargeError(_("File size exceeds maximum allowed."))

    if allowed_types:
        if not file.name:
            raise MissingFilenameError(_("Filename is required."))

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

        detected_mime = result.output.mime_type
        if detected_mime not in allowed_types:
            raise InvalidFileTypeError(_("File type not allowed."))

        file_ext = Path(file.name).suffix.lower()
        allowed_extensions = [ext.lower() for ext in allowed_types[detected_mime]]
        if file_ext not in allowed_extensions:
            raise ExtensionMismatchError(
                _("File extension does not match detected type.")
            )


def build_file_download_response(
    file: FieldFile,
    *,
    filename: str | None = None,
    content_type: str = "application/octet-stream",
    disposition: Literal["inline", "attachment"] = "inline",
) -> HttpResponse | StreamingHttpResponse:
    """Build a response for serving a stored file.

    Uses ``filename`` for the response filename, falling back to the file's basename.

    In Django mode, returns a ``FileResponse`` serving the file directly. In nginx mode,
    returns a response with ``X-Accel-Redirect`` header for nginx to serve the file.

    Raises:
        ValueError: If the file has no name or the path is invalid.
        FileNotFoundError: If the file does not exist (Django mode only).
    """
    if not file.name:
        raise ValueError("File has no name.")

    file_path = Path(file.name)
    has_drive_letter = (
        sys.platform == "win32"
        and len(file.name) >= 2
        and file.name[0].isalpha()
        and file.name[1] == ":"
    )
    if (
        "\\" in file.name
        or file_path.is_absolute()
        or file.name.startswith("/")
        or has_drive_letter
        or ".." in file_path.parts
    ):
        raise ValueError("Invalid file path.")

    if filename:
        # Sanitize backslashes before path processing to prevent Windows from
        # interpreting them as path separators.
        sanitized = filename.replace("\\", "_")
        resolved_filename = Path(sanitized).name
        if resolved_filename != sanitized:
            logger.error("filename contained path components.", filename=filename)
    else:
        resolved_filename = ""

    resolved_filename = resolved_filename or file_path.name

    if resolved_filename:
        # Sanitize for filesystem safety: remove control chars, backslashes, and quotes.
        safe_filename = "".join(
            c if c.isprintable() else "_" for c in resolved_filename
        )
        safe_filename = safe_filename.replace("\\", "_").replace('"', "_")

        # Build Content-Disposition with RFC 5987 encoding for non-ASCII filenames.
        ascii_filename = safe_filename.encode("ascii", errors="replace").decode()
        content_disposition = f'{disposition}; filename="{ascii_filename}"'
        if ascii_filename != safe_filename:
            encoded = quote(safe_filename, safe="")
            content_disposition += f"; filename*=UTF-8''{encoded}"
    else:
        logger.error(
            "Could not resolve filename for file.",
            file_name=file.name,
            provided_filename=filename,
        )
        content_disposition = disposition

    response: HttpResponse | StreamingHttpResponse
    if settings.FILE_DOWNLOAD_MODE == "nginx":
        prefix = settings.FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX.rstrip("/")
        encoded_path = quote(file.name, safe="/")
        internal_path = f"{prefix}/{encoded_path}"
        # Fallback message shown if nginx is misconfigured and doesn't honor
        # `X-Accel-Redirect`. Normally nginx replaces this with the actual file content.
        response = HttpResponse(
            "File download is temporarily unavailable. "
            "Please contact the site administrator.",
            content_type=content_type,
        )
        response[settings.FILE_DOWNLOAD_NGINX_HEADER] = internal_path
    else:
        response = FileResponse(file.open("rb"), content_type=content_type)

    response["Content-Disposition"] = content_disposition
    return response

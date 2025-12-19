from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from pytest_mock import MockerFixture

from app.utils.upload import (
    MAX_MEMORY_DETECTION_SIZE,
    ExtensionMismatchError,
    FileTooLargeError,
    InvalidFileTypeError,
    MissingFilenameError,
    get_magika,
    validate_upload,
)

# Expected test data files in tests/data/ directory.
SAMPLE_PNG = "sample.png"
SAMPLE_PDF = "sample.pdf"
SAMPLE_ZIP = "sample.zip"
SAMPLE_DOC = "sample.doc"
SAMPLE_DOCX = "sample.docx"

MOCK_MIME_PDF = "application/pdf"
MOCK_ALLOWED_TYPES = {MOCK_MIME_PDF: [".pdf"]}


@pytest.fixture
def temp_uploaded_file(tmp_path: Path) -> MagicMock:
    temp_file_path = tmp_path / "temp_upload.pdf"
    temp_file_path.write_bytes(b"fake content")
    file = MagicMock(spec=TemporaryUploadedFile)
    file.name = "upload.pdf"
    file.temporary_file_path.return_value = str(temp_file_path)
    return file


class TestValidateUpload:
    @pytest.fixture(autouse=True)
    def mock_magika(self, mocker: MockerFixture) -> MagicMock:
        instance = MagicMock()
        mocker.patch("app.utils.upload.get_magika", return_value=instance)

        result = MagicMock()
        result.output.mime_type = MOCK_MIME_PDF
        instance.identify_bytes.return_value = result
        instance.identify_path.return_value = result

        return instance

    def test_skip_size_check_when_max_size_is_zero(self) -> None:
        file = SimpleUploadedFile("large.txt", b"x" * 10_000)
        validate_upload(file, max_size=0)

    def test_skip_size_check_when_max_size_is_negative(self) -> None:
        file = SimpleUploadedFile("large.txt", b"x" * 10_000)
        validate_upload(file, max_size=-100)

    def test_size_check_passes_when_file_within_limit(self) -> None:
        file = SimpleUploadedFile("small.txt", b"hello")
        validate_upload(file, max_size=100)

    def test_size_check_passes_when_file_exactly_at_limit(self) -> None:
        content = b"x" * 100
        file = SimpleUploadedFile("exact.txt", content)
        validate_upload(file, max_size=100)

    def test_size_check_fails_when_file_exceeds_limit(self) -> None:
        file = SimpleUploadedFile("large.txt", b"x" * 101)
        with pytest.raises(
            FileTooLargeError,
            match="File size exceeds maximum allowed",
        ):
            validate_upload(file, max_size=100)

    def test_size_check_skipped_when_file_size_is_none(self) -> None:
        file = SimpleUploadedFile("test.txt", b"content")
        file.size = None
        validate_upload(file, max_size=1)

    def test_skip_type_check_when_allowed_types_none(
        self,
        mock_magika: MagicMock,
    ) -> None:
        file = SimpleUploadedFile("test.txt", b"content")

        validate_upload(file, allowed_types=None)

        mock_magika.identify_bytes.assert_not_called()
        mock_magika.identify_path.assert_not_called()

    def test_skip_type_check_when_allowed_types_empty_dict(
        self,
        mock_magika: MagicMock,
    ) -> None:
        file = SimpleUploadedFile("test.txt", b"content")

        validate_upload(file, allowed_types={})

        mock_magika.identify_bytes.assert_not_called()
        mock_magika.identify_path.assert_not_called()

    def test_type_check_uses_identify_path_for_temporary_file(
        self,
        temp_uploaded_file: MagicMock,
        mock_magika: MagicMock,
    ) -> None:
        validate_upload(temp_uploaded_file, allowed_types=MOCK_ALLOWED_TYPES)
        mock_magika.identify_path.assert_called_once_with(
            temp_uploaded_file.temporary_file_path()
        )
        mock_magika.identify_bytes.assert_not_called()

    def test_type_check_uses_identify_bytes_for_in_memory_file(
        self,
        mock_magika: MagicMock,
    ) -> None:
        content = b"file content"
        file = SimpleUploadedFile("test.pdf", content)

        validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

        mock_magika.identify_bytes.assert_called_once_with(content)
        mock_magika.identify_path.assert_not_called()

    def test_file_position_preserved_after_type_detection(self) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")

        file.seek(5)
        validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

        assert file.tell() == 5

    def test_type_check_passes_when_mime_type_allowed(self) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")
        allowed = {MOCK_MIME_PDF: [".pdf"], "other/mime": [".other"]}
        validate_upload(file, allowed_types=allowed)

    def test_type_check_fails_when_mime_type_not_allowed_for_in_memory_file(
        self,
    ) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")
        with pytest.raises(
            InvalidFileTypeError,
            match="File type not allowed",
        ):
            validate_upload(file, allowed_types={"disallowed/mime": [".pdf"]})

    def test_type_check_fails_when_mime_type_not_allowed_for_temporary_file(
        self,
        temp_uploaded_file: MagicMock,
    ) -> None:
        with pytest.raises(
            InvalidFileTypeError,
            match="File type not allowed",
        ):
            disallowed = {"disallowed/mime": [".pdf"]}
            validate_upload(temp_uploaded_file, allowed_types=disallowed)

    def test_raises_runtime_error_when_in_memory_file_too_large(self) -> None:
        large_content = b"x" * (MAX_MEMORY_DETECTION_SIZE + 1)
        file = SimpleUploadedFile("large.bin", large_content)

        with pytest.raises(RuntimeError) as exc_info:
            validate_upload(file, allowed_types={"application/octet-stream": [".bin"]})

        error_msg = str(exc_info.value)
        assert "In-memory file too large" in error_msg
        assert str(MAX_MEMORY_DETECTION_SIZE) in error_msg
        assert "TemporaryUploadedFile" in error_msg

    def test_accepts_file_at_memory_limit_boundary(self) -> None:
        boundary_content = b"x" * MAX_MEMORY_DETECTION_SIZE
        file = SimpleUploadedFile("boundary.pdf", boundary_content)
        validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

    def test_size_checked_before_type(
        self,
        mock_magika: MagicMock,
    ) -> None:
        file = SimpleUploadedFile("test.pdf", b"x" * 100)

        with pytest.raises(FileTooLargeError):
            validate_upload(file, max_size=50, allowed_types=MOCK_ALLOWED_TYPES)

        mock_magika.identify_bytes.assert_not_called()
        mock_magika.identify_path.assert_not_called()

    def test_both_checks_pass(self) -> None:
        file = SimpleUploadedFile("test.pdf", b"content")
        validate_upload(file, max_size=100, allowed_types=MOCK_ALLOWED_TYPES)

    def test_missing_filename_raises_error(self) -> None:
        file = MagicMock()
        file.name = ""
        file.size = 100
        with pytest.raises(
            MissingFilenameError,
            match="Filename is required",
        ):
            validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

    def test_none_filename_raises_error(self) -> None:
        file = MagicMock()
        file.name = None
        file.size = 100
        with pytest.raises(
            MissingFilenameError,
            match="Filename is required",
        ):
            validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

    def test_missing_filename_not_checked_when_allowed_types_none(self) -> None:
        file = MagicMock()
        file.name = ""
        file.size = 100
        validate_upload(file, allowed_types=None)

    def test_extension_mismatch_raises_error(self) -> None:
        file = SimpleUploadedFile("document.txt", b"content")
        with pytest.raises(
            ExtensionMismatchError,
            match="File extension does not match detected type",
        ):
            validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

    def test_extension_check_is_case_insensitive(self) -> None:
        file = SimpleUploadedFile("document.PDF", b"content")
        validate_upload(file, allowed_types=MOCK_ALLOWED_TYPES)

    def test_extension_check_with_uppercase_in_allowed_types(self) -> None:
        file = SimpleUploadedFile("document.pdf", b"content")
        validate_upload(file, allowed_types={MOCK_MIME_PDF: [".PDF"]})

    def test_get_magika_returns_same_instance_on_multiple_calls(self) -> None:
        get_magika.cache_clear()
        first = get_magika()
        second = get_magika()
        assert first is second


class TestValidateUploadE2E:
    @pytest.fixture(autouse=True)
    def clear_magika_cache(self) -> None:
        get_magika.cache_clear()

    @pytest.mark.parametrize(
        ("filename", "allowed_types"),
        [
            (SAMPLE_PNG, {"image/png": [".png"]}),
            (SAMPLE_PDF, {"application/pdf": [".pdf"]}),
            (SAMPLE_ZIP, {"application/zip": [".zip"]}),
            (SAMPLE_DOC, {"application/msword": [".doc"]}),
            (
                SAMPLE_DOCX,
                {
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document": [".docx"]
                },
            ),
        ],
    )
    def test_magika_identifies_file_type_correctly(
        self,
        test_data_dir: Path,
        filename: str,
        allowed_types: dict[str, list[str]],
    ) -> None:
        file_path = test_data_dir / filename
        if not file_path.exists():
            pytest.skip(f"Test file not found: {file_path}")

        content = file_path.read_bytes()
        file = SimpleUploadedFile(filename, content)

        validate_upload(file, allowed_types=allowed_types)

    @pytest.mark.parametrize(
        ("filename", "disallowed_allowed_types"),
        [
            (SAMPLE_PNG, {"application/pdf": [".png"]}),
            (SAMPLE_PDF, {"image/png": [".pdf"]}),
            (SAMPLE_ZIP, {"text/plain": [".zip"]}),
            # DOCX is ZIP-based but Magika correctly distinguishes it.
            (SAMPLE_DOCX, {"application/zip": [".docx"]}),
        ],
    )
    def test_magika_rejects_mismatched_types(
        self,
        test_data_dir: Path,
        filename: str,
        disallowed_allowed_types: dict[str, list[str]],
    ) -> None:
        file_path = test_data_dir / filename
        if not file_path.exists():
            pytest.skip(f"Test file not found: {file_path}")

        content = file_path.read_bytes()
        file = SimpleUploadedFile(filename, content)

        with pytest.raises(InvalidFileTypeError):
            validate_upload(file, allowed_types=disallowed_allowed_types)

    def test_magika_with_temporary_uploaded_file(
        self,
        test_data_dir: Path,
        tmp_path: Path,
    ) -> None:
        png_path = test_data_dir / SAMPLE_PNG
        if not png_path.exists():
            pytest.skip(f"Test file not found: {png_path}")

        temp_file_path = tmp_path / "upload.png"
        temp_file_path.write_bytes(png_path.read_bytes())

        file = MagicMock(spec=TemporaryUploadedFile)
        file.name = "upload.png"
        file.temporary_file_path.return_value = str(temp_file_path)
        file.size = temp_file_path.stat().st_size

        validate_upload(file, allowed_types={"image/png": [".png"]})

    def test_combined_size_and_type_validation(self, test_data_dir: Path) -> None:
        png_path = test_data_dir / SAMPLE_PNG
        if not png_path.exists():
            pytest.skip(f"Test file not found: {png_path}")

        content = png_path.read_bytes()
        file = SimpleUploadedFile(SAMPLE_PNG, content)

        validate_upload(
            file,
            max_size=len(content) + 100,
            allowed_types={"image/png": [".png"]},
        )

        small_file = SimpleUploadedFile(SAMPLE_PNG, content)
        with pytest.raises(FileTooLargeError):
            validate_upload(
                small_file,
                max_size=10,
                allowed_types={"image/png": [".png"]},
            )

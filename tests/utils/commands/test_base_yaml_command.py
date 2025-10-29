from pathlib import Path
from textwrap import dedent

import pytest
from django.core.management.base import CommandError, CommandParser
from pydantic import BaseModel, Field, ValidationError

from app.utils.commands import BaseYAMLCommand


def write_yaml(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class SimpleSchema(BaseModel):
    """Test schema for BaseYAMLCommand tests."""

    name: str = Field(min_length=1)
    items: list[str] = Field(default_factory=list)


class SimpleCommand(BaseYAMLCommand):
    """Minimal command for testing BaseYAMLCommand functionality."""

    def add_arguments(self, parser: CommandParser) -> None:  # pragma: no cover
        parser.add_argument("directory", type=Path)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *_: object, directory: Path, strict: bool, **__: object) -> None:
        yaml_files = self.collect_yaml_files(directory)
        if not yaml_files:
            self.stdout.write(self.style.WARNING("No YAML files found."))
            return

        skipped: list[str] = []
        for file_path in yaml_files:
            try:
                self.load_yaml_file(file_path, SimpleSchema)
            except Exception as exc:
                self.handle_file_errors(file_path, exc, strict=strict, skipped=skipped)

        if skipped:
            for message in skipped:
                self.stderr.write(self.style.WARNING(message))


class TestCollectYAMLFiles:
    def test_collect_yaml_files_success(self, tmp_path: Path) -> None:
        (tmp_path / "file1.yaml").touch()
        (tmp_path / "file2.yml").touch()
        (tmp_path / "file3.txt").touch()
        (tmp_path / "subdir").mkdir()

        files = BaseYAMLCommand.collect_yaml_files(tmp_path)

        assert len(files) == 2
        assert all(f.suffix.lower() in {".yaml", ".yml"} for f in files)
        assert files == sorted(files)

    def test_collect_yaml_files_empty_directory(self, tmp_path: Path) -> None:
        files = BaseYAMLCommand.collect_yaml_files(tmp_path)
        assert files == []

    def test_collect_yaml_files_missing_directory(self, tmp_path: Path) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            BaseYAMLCommand.collect_yaml_files(tmp_path / "missing")

    def test_collect_yaml_files_path_is_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.yaml"
        file_path.touch()

        with pytest.raises(CommandError, match="not a directory"):
            BaseYAMLCommand.collect_yaml_files(file_path)


class TestLoadYAMLFile:
    def test_load_yaml_file_success(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.yaml"
        write_yaml(file_path, "name: Test\nitems: [a, b, c]")

        result = BaseYAMLCommand.load_yaml_file(file_path, SimpleSchema)

        assert result.name == "Test"
        assert result.items == ["a", "b", "c"]

    def test_load_yaml_file_with_defaults(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.yaml"
        write_yaml(file_path, "name: Test")

        result = BaseYAMLCommand.load_yaml_file(file_path, SimpleSchema)

        assert result.name == "Test"
        assert result.items == []

    def test_load_yaml_file_validation_error(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.yaml"
        write_yaml(file_path, "name: ''\nitems: []")

        with pytest.raises(ValidationError):
            BaseYAMLCommand.load_yaml_file(file_path, SimpleSchema)


class TestHandleFileErrors:
    def test_handle_file_errors_strict_mode(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.yaml"
        exc = ValueError("Test error")
        skipped: list[str] = []

        with pytest.raises(CommandError, match="Test error"):
            BaseYAMLCommand.handle_file_errors(
                file_path,
                exc,
                strict=True,
                skipped=skipped,
            )

        assert not skipped

    def test_handle_file_errors_non_strict_mode(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.yaml"
        exc = ValueError("Test error")
        skipped: list[str] = []

        BaseYAMLCommand.handle_file_errors(
            file_path,
            exc,
            strict=False,
            skipped=skipped,
        )

        assert len(skipped) == 1
        assert "test.yaml" in skipped[0]
        assert "Test error" in skipped[0]


class TestIntegration:
    def test_no_yaml_files(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        command = SimpleCommand()
        command.handle(directory=tmp_path, strict=False)

        captured = capsys.readouterr()
        assert "No YAML files found." in captured.out

    def test_missing_directory(self, tmp_path: Path) -> None:
        command = SimpleCommand()

        with pytest.raises(CommandError, match="does not exist"):
            command.handle(directory=tmp_path / "missing", strict=False)

    def test_path_is_not_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.yaml"
        write_yaml(file_path, "name: Test")

        command = SimpleCommand()

        with pytest.raises(CommandError, match="not a directory"):
            command.handle(directory=file_path, strict=False)

    def test_invalid_yaml_non_strict(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        write_yaml(tmp_path / "bad.yaml", "name: test items: [oops")

        command = SimpleCommand()
        command.handle(directory=tmp_path, strict=False)

        captured = capsys.readouterr()
        assert "bad.yaml" in captured.err

    def test_invalid_yaml_strict(self, tmp_path: Path) -> None:
        write_yaml(tmp_path / "bad.yaml", "name: test items: [oops")

        command = SimpleCommand()

        with pytest.raises(CommandError):
            command.handle(directory=tmp_path, strict=True)

    def test_validation_error_non_strict(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        write_yaml(tmp_path / "invalid.yaml", "name: ''\nitems: []")

        command = SimpleCommand()
        command.handle(directory=tmp_path, strict=False)

        captured = capsys.readouterr()
        assert "invalid.yaml" in captured.err

    def test_validation_error_strict(self, tmp_path: Path) -> None:
        write_yaml(tmp_path / "invalid.yaml", "name: ''\nitems: []")

        command = SimpleCommand()

        with pytest.raises(CommandError):
            command.handle(directory=tmp_path, strict=True)

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from pydantic import BaseModel


class BaseYAMLCommand(BaseCommand):
    """Base class for management commands that load data from YAML files."""

    @classmethod
    def collect_yaml_files(cls, directory: Path) -> list[Path]:
        """Return all YAML files within the provided directory.

        Args:
            directory: Directory to search for YAML files.

        Returns:
            Sorted list of YAML file paths.

        Raises:
            CommandError: If directory does not exist or is not a directory.
        """
        if not directory.exists():
            raise CommandError(f"Directory '{directory}' does not exist.")
        if not directory.is_dir():
            raise CommandError(f"Path '{directory}' is not a directory.")

        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
        )

    @classmethod
    def load_yaml_file[T: BaseModel](cls, path: Path, schema: type[T]) -> T:
        """Load a single YAML file and validate against a Pydantic schema.

        Args:
            path: Path to the YAML file.
            schema: Pydantic model class to validate against.

        Returns:
            Validated Pydantic model instance.

        Raises:
            OSError: If file cannot be read.
            YAMLError: If YAML is malformed.
            ValidationError: If data does not match schema.
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return schema.model_validate(data or {})

    @classmethod
    def handle_file_errors(
        cls,
        file_path: Path,
        exc: Exception,
        *,
        strict: bool,
        skipped: list[str],
    ) -> None:
        """Handle errors that occur while processing a file.

        Args:
            file_path: Path to the file that caused the error.
            exc: The exception that was raised.
            strict: If ``True``, re-raise as CommandError. If ``False``, add to skipped
                list.
            skipped: List to append error messages to when not in strict mode.

        Raises:
            CommandError: If strict mode is enabled.
        """
        message = f"{file_path}: {exc}"
        if strict:
            raise CommandError(message) from exc
        skipped.append(message)

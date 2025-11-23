from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import CommandError, CommandParser
from django.db import transaction
from pydantic import BaseModel, Field, ValidationError, field_validator
from yaml import YAMLError

from app.conference.models import Keyword, KeywordSet
from app.utils.commands import BaseYAMLCommand
from app.utils.sanitization import sanitize_text


class KeywordSetDefinition(BaseModel):
    """Represents a keyword set definition loaded from YAML."""

    name: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _sanitize_name(cls, value: str) -> str:
        """Normalize keyword set names using shared sanitizer."""
        return sanitize_text(value)

    @field_validator("keywords")
    @classmethod
    def _strip_keywords(cls, values: list[str]) -> list[str]:
        """Normalize keyword text values."""
        cleaned_keywords = []
        for value in values:
            sanitized = sanitize_text(value)
            if sanitized:
                cleaned_keywords.append(sanitized)
        return cleaned_keywords


class Command(BaseYAMLCommand):
    """Load keyword sets from YAML files."""

    help = "Load keyword sets from YAML sources."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "directory",
            nargs="?",
            type=Path,
            default=settings.BASE_DIR / "seed" / "keywords",
            help="Directory containing YAML keyword set definitions.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Abort if any file fails schema validation.",
        )

    def handle(
        self,
        *_: Any,
        directory: Path,
        strict: bool,
        **__: Any,
    ) -> None:
        yaml_files = self.collect_yaml_files(directory)
        if not yaml_files:  # pragma: no cover
            self.stdout.write(self.style.WARNING("No YAML files found."))
            return

        definitions, skipped = self._load_definitions(yaml_files, strict=strict)

        if skipped:
            for message in skipped:
                self.stderr.write(self.style.WARNING(message))
            self.stderr.write(
                self.style.WARNING(f"{len(skipped)} file(s) skipped due to errors.")
            )

        if not definitions:  # pragma: no cover
            self.stdout.write(self.style.NOTICE("No keyword sets to load."))
            return

        self._load_keywords(definitions)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(definitions)} keyword set(s) successfully."
            )
        )

    def _load_definitions(
        self,
        yaml_files: list[Path],
        *,
        strict: bool,
    ) -> tuple[list[KeywordSetDefinition], list[str]]:
        """Load and validate keyword set definitions from YAML files."""
        definitions: list[KeywordSetDefinition] = []
        skipped: list[str] = []
        seen_names: dict[str, Path] = {}

        for file_path in yaml_files:
            try:
                definition = self.load_yaml_file(file_path, KeywordSetDefinition)
            except (OSError, YAMLError, ValidationError) as exc:  # pragma: no cover
                self.handle_file_errors(file_path, exc, strict=strict, skipped=skipped)
                continue

            # Check for duplicate names across files.
            if definition.name in seen_names:
                previous_path = seen_names[definition.name]
                message = (
                    f"{file_path}: Duplicate keyword set name {definition.name!r}. "
                    f"Previously defined in {previous_path}."
                )
                if strict:
                    raise CommandError(message)
                skipped.append(message)
                continue

            seen_names[definition.name] = file_path
            definitions.append(definition)

        return definitions, skipped

    def _load_keywords(self, definitions: list[KeywordSetDefinition]) -> None:
        """Load keyword sets into the database."""
        with transaction.atomic():
            for definition in definitions:
                keyword_set, created = KeywordSet.objects.get_or_create(
                    name=definition.name,
                )

                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f"Created keyword set {definition.name!r}.")
                    )

                Keyword.objects.bulk_create(
                    [Keyword(text=text) for text in definition.keywords],
                    ignore_conflicts=True,
                )
                keyword_set.keywords.set(
                    Keyword.objects.filter(text__in=definition.keywords)
                )

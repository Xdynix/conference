from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from pydantic import BaseModel, Field, ValidationError, field_validator
from yaml import YAMLError

from app.core.models import AbstractRole, Permission


class RoleDefinition(BaseModel):
    """Represents a single role definition loaded from YAML."""

    model: str = Field(min_length=1)
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def _strip_permissions(cls, values: list[str]) -> list[str]:
        """Normalize permission identifiers."""
        return [value.strip() for value in values if value.strip()]

    def split_content(self) -> tuple[dict[str, Any], set[str]]:
        """Return model field data and associated permission keys."""
        content = self.model_dump()
        permission_keys = set(content.pop("permissions", ()))
        content.pop("model", None)
        return content, permission_keys


class RoleFile(BaseModel):
    """Represents the contents of a YAML file."""

    roles: list[RoleDefinition] = Field(default_factory=list)


@dataclass(slots=True)
class CreatePlan:
    """Represents a new role to be created."""

    model: type[AbstractRole]
    data: dict[str, Any]
    permissions: set[str]
    source: Path

    @property
    def name(self) -> Any:
        return self.data.get("name")


@dataclass(slots=True)
class UpdatePlan:
    """Represents an existing role to be updated."""

    model: type[AbstractRole]
    pk: Any
    data: dict[str, Any]
    permissions: set[str]
    field_changes: dict[str, tuple[Any, Any]]
    permission_additions: set[str]
    permission_removals: set[str]
    source: Path


@dataclass(slots=True)
class DeletePlan:
    """Represents a role that should be deleted."""

    model: type[AbstractRole]
    pk: Any
    display_name: str


@dataclass(slots=True)
class SyncPlan:
    """Collection of planned actions."""

    create: list[CreatePlan]
    update: list[UpdatePlan]
    delete: list[DeletePlan]


class Command(BaseCommand):
    """Synchronize role definitions from YAML files."""

    help = "Sync role definitions from YAML sources."

    def add_arguments(self, parser: CommandParser) -> None:  # pragma: no cover
        parser.add_argument(
            "directory",
            nargs="?",
            type=Path,
            default=settings.BASE_DIR / "seed" / "roles",
            help="Directory containing YAML role definitions.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Abort if any file fails schema validation.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete roles that are not declared in the YAML files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them.",
        )

    def handle(
        self,
        *_: Any,
        directory: Path,
        strict: bool,
        prune: bool,
        dry_run: bool,
        **__: Any,
    ) -> None:
        yaml_files = self._collect_yaml_files(directory)
        if not yaml_files:
            self.stdout.write(self.style.WARNING("No YAML files found."))
            return

        plan, skipped = self._plan(yaml_files, strict=strict, prune=prune)

        if skipped:
            for message in skipped:
                self.stderr.write(self.style.WARNING(message))
            self.stderr.write(
                self.style.WARNING(f"{len(skipped)} file(s) skipped due to errors.")
            )

        if not plan.create and not plan.update and not plan.delete:
            self.stdout.write(self.style.NOTICE("Roles are already up to date."))
            return

        permission_lookup = self._ensure_permissions(
            self._collect_permission_keys(plan)
        )

        self._render_plan(plan)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode: no changes applied."))
            return

        self._apply(plan, permission_lookup)
        self.stdout.write(self.style.SUCCESS("Role synchronization complete."))

    @classmethod
    def _collect_yaml_files(cls, directory: Path) -> list[Path]:
        """Return all YAML files within the provided directory."""
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
    def _load_role_file(cls, path: Path) -> RoleFile:
        """Load a single YAML file into the role schema."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RoleFile.model_validate(data or {})

    def _plan(
        self,
        yaml_files: list[Path],
        *,
        strict: bool,
        prune: bool,
    ) -> tuple[SyncPlan, list[str]]:
        """Build a plan of actions without mutating the database."""
        collected: dict[
            type[AbstractRole],
            dict[str, tuple[dict[str, Any], set[str], Path]],
        ] = defaultdict(dict)
        skipped: list[str] = []

        for file_path in yaml_files:
            try:
                role_file = self._load_role_file(file_path)
            except (OSError, YAMLError, ValidationError) as exc:
                message = f"{file_path}: {exc}"
                if strict:
                    raise CommandError(message) from exc
                skipped.append(message)
                continue

            for definition in role_file.roles:
                try:
                    model_class = self._resolve_model(definition.model)
                except ValueError as exc:
                    message = f"{file_path}: {exc}"
                    if strict:
                        raise CommandError(message) from exc
                    skipped.append(message)
                    continue

                fields, permissions = definition.split_content()
                pk_name = model_class._meta.pk.name
                pk_value = fields.get(pk_name)
                if pk_value is None:
                    message = (
                        f"{file_path}: "
                        f"Missing required primary key field '{pk_name}' "
                        f"for model {model_class.__name__}."
                    )
                    if strict:
                        raise CommandError(message)
                    skipped.append(message)
                    continue

                try:
                    self._validate_fields(model_class, fields)
                except CommandError as exc:
                    message = f"{file_path}: {exc}"
                    if strict:
                        raise CommandError(message) from exc
                    skipped.append(message)
                    continue

                previous = collected[model_class].get(str(pk_value))
                if previous:
                    previous_path = previous[2]
                    message = (
                        f"{file_path}: Duplicate role '{pk_value}' "
                        f"for model {model_class.__name__}. "
                        f"Previously defined in {previous_path}."
                    )
                    if strict:
                        raise CommandError(message)
                    skipped.append(message)
                    continue

                collected[model_class][str(pk_value)] = (fields, permissions, file_path)

        plan = SyncPlan(create=[], update=[], delete=[])
        for model_class, definitions in collected.items():
            existing = {
                str(role.pk): role
                for role in model_class.objects.prefetch_related("permissions").all()  # type: ignore[attr-defined]
            }

            for pk_value, (fields, permissions, source) in definitions.items():
                role = existing.get(pk_value)
                prepared_permissions = set(permissions)
                if role is None:
                    plan.create.append(
                        CreatePlan(
                            model=model_class,
                            data=fields,
                            permissions=prepared_permissions,
                            source=source,
                        )
                    )
                    continue

                field_changes: dict[str, tuple[Any, Any]] = {}
                for attr, value in fields.items():
                    if getattr(role, attr) != value:
                        field_changes[attr] = (getattr(role, attr), value)

                current_permissions = {perm.key for perm in role.permissions.all()}
                permission_additions = prepared_permissions - current_permissions
                permission_removals = current_permissions - prepared_permissions

                if (
                    not field_changes
                    and not permission_additions
                    and not permission_removals
                ):
                    continue

                plan.update.append(
                    UpdatePlan(
                        model=model_class,
                        pk=pk_value,
                        data=fields,
                        permissions=prepared_permissions,
                        field_changes=field_changes,
                        permission_additions=permission_additions,
                        permission_removals=permission_removals,
                        source=source,
                    )
                )

            if prune:
                desired_keys = set(definitions)
                for pk_value, role in existing.items():
                    if pk_value not in desired_keys:
                        plan.delete.append(
                            DeletePlan(
                                model=model_class,
                                pk=pk_value,
                                display_name=role.display_name,
                            )
                        )

        return plan, skipped

    @classmethod
    def _resolve_model(cls, label: str) -> type[AbstractRole]:
        """Resolve the ``app_label.model_name`` string to a role class."""
        if "." not in label:
            raise ValueError("Model must be specified as 'app_label.model_name'.")

        app_label, model_name = label.split(".", 1)
        if not app_label or not model_name:
            raise ValueError("Model must be specified as 'app_label.model_name'.")

        try:
            model_class = apps.get_model(
                app_label=app_label,
                model_name=model_name,
            )
        except LookupError as exc:
            raise ValueError(f"Could not resolve model '{label}': {exc}") from exc

        if not issubclass(model_class, AbstractRole):
            raise ValueError(f"Model '{label}' does not inherit from AbstractRole.")

        return model_class

    @classmethod
    def _validate_fields(
        cls,
        model_class: type[AbstractRole],
        fields: dict[str, Any],
    ) -> None:
        """Ensure provided fields exist on the model."""
        for field_name in fields:
            try:
                model_class._meta.get_field(field_name)
            except FieldDoesNotExist as exc:
                raise CommandError(
                    f"Field '{field_name}' does not exist "
                    f"on model {model_class.__name__}."
                ) from exc

    def _render_plan(self, plan: SyncPlan) -> None:
        """Output the planned actions."""
        for create in plan.create:
            model_name = create.model.__name__
            name = create.name
            location = create.source.name
            self.stdout.write(
                self.style.SUCCESS(
                    f"[Create] {model_name} '{name}' (source: {location})"
                )
            )
            if create.permissions:  # pragma: no cover
                formatted = ", ".join(sorted(create.permissions))
                self.stdout.write(f"  permissions: +{formatted}")

        for update in plan.update:
            model_name = update.model.__name__
            location = update.source.name
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"[Update] {model_name} '{update.pk}' (source: {location})"
                )
            )
            for attr, (old, new) in update.field_changes.items():
                self.stdout.write(f"  {attr}: '{old}' -> '{new}'")
            if (
                update.permission_additions or update.permission_removals
            ):  # pragma: no cover
                additions = ", ".join(sorted(update.permission_additions))
                removals = ", ".join(sorted(update.permission_removals))
                if additions:
                    self.stdout.write(f"  permissions: +{additions}")
                if removals:
                    self.stdout.write(f"  permissions: -{removals}")

        for delete in plan.delete:
            model_name = delete.model.__name__
            self.stdout.write(
                self.style.WARNING(
                    f"[Delete] {model_name} '{delete.pk}' ({delete.display_name})"
                )
            )

        planned = len(plan.create) + len(plan.update) + len(plan.delete)
        self.stdout.write(self.style.NOTICE(f"{planned} change(s) planned."))

    def _apply(
        self,
        plan: SyncPlan,
        permission_lookup: dict[str, Permission],
    ) -> None:
        """Apply the planned actions within a transaction."""
        with transaction.atomic():
            for create in plan.create:
                instance = create.model(**create.data)
                instance.full_clean()
                instance.save()
                self._assign_permissions(
                    instance,
                    create.permissions,
                    permission_lookup,
                )

            for update in plan.update:
                instance = update.model.objects.select_for_update().get(pk=update.pk)  # type: ignore[attr-defined]
                update_fields: list[str] = []
                for attr, (_, new_value) in update.field_changes.items():
                    setattr(instance, attr, new_value)
                    update_fields.append(attr)

                if update_fields:
                    instance.full_clean()
                    instance.save(update_fields=update_fields)

                self._assign_permissions(
                    instance,
                    update.permissions,
                    permission_lookup,
                )

            for delete in plan.delete:
                delete.model.objects.filter(pk=delete.pk).delete()  # type: ignore[attr-defined]

    @classmethod
    def _assign_permissions(
        cls,
        instance: AbstractRole,
        permissions: set[str],
        permission_lookup: dict[str, Permission],
    ) -> None:
        """Assign the provided permission keys to the instance."""
        resolved = [permission_lookup[key] for key in sorted(permissions)]
        instance.permissions.set(resolved)

    @classmethod
    def _collect_permission_keys(cls, plan: SyncPlan) -> set[str]:
        """Gather all permission keys referenced in the plan."""
        keys: set[str] = set()
        for create in plan.create:
            keys.update(create.permissions)
        for update in plan.update:
            keys.update(update.permissions)
        return keys

    @classmethod
    def _ensure_permissions(cls, keys: set[str]) -> dict[str, Permission]:
        """Return Permission objects for the provided keys.

        Raises:
            CommandError: If any requested permissions are not present.
        """
        if not keys:
            return {}

        existing = {
            permission.key: permission
            for permission in Permission.objects.filter(key__in=keys)
        }
        missing = sorted(keys - existing.keys())
        if missing:
            missing_list = ", ".join(missing)
            raise CommandError(
                f"Permissions missing from the database: {missing_list}."
            )

        return existing

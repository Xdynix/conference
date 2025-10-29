from pathlib import Path
from textwrap import dedent

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest_mock import MockerFixture

from app.core.management.commands.sync_roles import RoleDefinition
from app.core.models import Permission, Role


def write_yaml(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


@pytest.mark.django_db
def test_handle_creates_and_updates_roles(tmp_path: Path) -> None:
    Permission.objects.bulk_create(
        [
            Permission(key="test.sync_roles.admin"),
            Permission(key="test.sync_roles.read"),
            Permission(key="test.sync_roles.write"),
        ]
    )

    existing = Role.objects.create(
        name="viewer",
        display_name="Viewer",
        description="Can view data.",
    )
    existing.permissions.set(Permission.objects.filter(key="test.sync_roles.read"))

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: editor
            display_name: Editor
            description: Allows content editing.
            permissions:
              - test.sync_roles.read
              - test.sync_roles.write
          - model: core.role
            name: viewer
            display_name: Power Viewer
            description: Updated description.
            permissions:
              - test.sync_roles.read
              - test.sync_roles.admin
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    editor = Role.objects.get(name="editor")
    assert editor.display_name == "Editor"
    assert editor.description == "Allows content editing."
    assert set(editor.permissions.values_list("key", flat=True)) == {
        "test.sync_roles.read",
        "test.sync_roles.write",
    }

    existing.refresh_from_db()
    assert existing.display_name == "Power Viewer"
    assert existing.description == "Updated description."
    assert set(existing.permissions.values_list("key", flat=True)) == {
        "test.sync_roles.read",
        "test.sync_roles.admin",
    }


@pytest.mark.django_db
def test_handle_prune_removes_missing_roles(tmp_path: Path) -> None:
    Permission.objects.bulk_create([Permission(key="test.sync_roles.read")])

    retained = Role.objects.create(
        name="retained",
        display_name="Retained Role",
        description="",
    )
    retained.permissions.set(Permission.objects.filter(key="test.sync_roles.read"))
    Role.objects.create(
        name="removed",
        display_name="Removed Role",
        description="",
    )

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: retained
            display_name: Retained Role
            description: ""
            permissions:
              - test.sync_roles.read
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=True,
        dry_run=False,
    )

    assert Role.objects.filter(name="retained").exists()
    assert not Role.objects.filter(name="removed").exists()


@pytest.mark.django_db
def test_handle_updates_permissions_only(tmp_path: Path) -> None:
    Permission.objects.bulk_create(
        [
            Permission(key="test.sync_roles.read"),
            Permission(key="test.sync_roles.write"),
        ]
    )

    role = Role.objects.create(
        name="manager",
        display_name="Manager",
        description="",
    )
    role.permissions.set(Permission.objects.filter(key="test.sync_roles.read"))

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: manager
            display_name: Manager
            description: ""
            permissions:
              - test.sync_roles.write
          - model: core.role
            name: assistant
            display_name: Assistant
            description: ""
            permissions: []
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    role.refresh_from_db()
    assert set(role.permissions.values_list("key", flat=True)) == {
        "test.sync_roles.write"
    }
    assistant = Role.objects.get(name="assistant")
    assert not assistant.permissions.exists()


@pytest.mark.django_db
def test_handle_updates_fields_only(tmp_path: Path) -> None:
    Permission.objects.bulk_create([Permission(key="test.sync_roles.read")])

    role = Role.objects.create(
        name="editor",
        display_name="Old",
        description="Old",
    )
    role.permissions.set(Permission.objects.filter(key="test.sync_roles.read"))

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: editor
            display_name: New
            description: Newer
            permissions:
              - test.sync_roles.read
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    role.refresh_from_db()
    assert role.display_name == "New"
    assert role.description == "Newer"


@pytest.mark.django_db
def test_handle_renders_plan_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    Permission.objects.bulk_create(
        [
            Permission(key="test.sync_roles.extra"),
            Permission(key="test.sync_roles.read"),
            Permission(key="test.sync_roles.write"),
        ]
    )

    role = Role.objects.create(
        name="updatable",
        display_name="Old",
        description="Old description",
    )
    role.permissions.set(Permission.objects.filter(key="test.sync_roles.write"))
    Role.objects.create(
        name="stale",
        display_name="Stale",
        description="Remove this role",
    )

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: creator
            display_name: Creator
            description: Creates things.
            permissions:
              - test.sync_roles.extra
          - model: core.role
            name: updatable
            display_name: New
            description: New description
            permissions:
              - test.sync_roles.read
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=True,
        dry_run=True,
    )

    captured = capsys.readouterr()
    assert "[Create]" in captured.out
    assert "[Update]" in captured.out
    assert "[Delete]" in captured.out


@pytest.mark.django_db
def test_handle_dry_run_does_not_change_database(tmp_path: Path) -> None:
    Permission.objects.bulk_create([Permission(key="test.sync_roles.read")])
    Role.objects.create(
        name="existing",
        display_name="Existing",
        description="Original description",
    )

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: existing
            display_name: Updated
            description: Updated description
            permissions:
              - test.sync_roles.read
          - model: core.role
            name: new
            display_name: New Role
            description: Brand new role
            permissions:
              - test.sync_roles.read
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=True,
        dry_run=True,
    )

    role = Role.objects.get(name="existing")
    assert role.display_name == "Existing"
    assert role.description == "Original description"
    assert not Role.objects.filter(name="new").exists()


@pytest.mark.django_db
def test_handle_roles_already_up_to_date(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    Permission.objects.bulk_create([Permission(key="test.sync_roles.read")])

    role = Role.objects.create(
        name="existing",
        display_name="Existing",
        description="Already synced.",
    )
    role.permissions.set(Permission.objects.filter(key="test.sync_roles.read"))

    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: existing
            display_name: Existing
            description: Already synced.
            permissions:
              - test.sync_roles.read
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    captured = capsys.readouterr()
    assert "Roles are already up to date." in captured.out


@pytest.mark.django_db
def test_handle_skips_invalid_model_non_strict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_yaml(
        tmp_path / "role.yaml",
        """
        roles:
          - model: missing_app.stub
            name: stub
            display_name: Stub
            description: ""
            permissions: []
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    captured = capsys.readouterr()
    assert "missing_app.stub" in captured.err


@pytest.mark.django_db
def test_handle_skips_duplicate_roles_non_strict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_yaml(
        tmp_path / "a.yaml",
        """
        roles:
          - model: core.role
            name: duplicate
            display_name: Duplicate
            description: ""
            permissions: []
        """,
    )
    write_yaml(
        tmp_path / "b.yaml",
        """
        roles:
          - model: core.role
            name: duplicate
            display_name: Duplicate
            description: ""
            permissions: []
        """,
    )

    call_command(
        "sync_roles",
        str(tmp_path),
        strict=False,
        prune=False,
        dry_run=False,
    )

    captured = capsys.readouterr()
    assert "Duplicate role 'duplicate'" in captured.err


@pytest.mark.django_db
@pytest.mark.parametrize("strict", [False, True])
def test_handle_missing_primary_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    strict: bool,
) -> None:
    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: missing
            display_name: Missing
            description: ""
            permissions: []
        """,
    )

    original_split = RoleDefinition.split_content

    def remove_pk(self: RoleDefinition) -> tuple[dict[str, str], set[str]]:
        fields, permissions = original_split(self)
        fields.pop("name", None)
        return fields, permissions

    mocker.patch.object(
        RoleDefinition,
        "split_content",
        autospec=True,
        side_effect=remove_pk,
    )

    if strict:
        with pytest.raises(CommandError):
            call_command(
                "sync_roles",
                str(tmp_path),
                strict=strict,
                prune=False,
                dry_run=False,
            )
    else:
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=strict,
            prune=False,
            dry_run=False,
        )
        captured = capsys.readouterr()
        assert "Missing required primary key field" in captured.err


@pytest.mark.django_db
@pytest.mark.parametrize("strict", [False, True])
def test_handle_invalid_fields(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    strict: bool,
) -> None:
    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: bad
            display_name: Bad
            description: ""
            permissions: []
        """,
    )

    original_split = RoleDefinition.split_content

    def add_unknown_field(self: RoleDefinition) -> tuple[dict[str, str], set[str]]:
        fields, permissions = original_split(self)
        fields["unknown_field"] = "value"
        return fields, permissions

    mocker.patch.object(
        RoleDefinition,
        "split_content",
        autospec=True,
        side_effect=add_unknown_field,
    )

    if strict:
        with pytest.raises(CommandError):
            call_command(
                "sync_roles",
                str(tmp_path),
                strict=strict,
                prune=False,
                dry_run=False,
            )
    else:
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=strict,
            prune=False,
            dry_run=False,
        )
        captured = capsys.readouterr()
        assert "Field 'unknown_field'" in captured.err


@pytest.mark.django_db
def test_handle_invalid_model_format(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.
            name: invalid
            display_name: Invalid
            description: ""
            permissions: []
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )


@pytest.mark.django_db
def test_handle_invalid_model_missing_dot(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: invalidmodel
            name: invalid
            display_name: Invalid
            description: ""
            permissions: []
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )


@pytest.mark.django_db
def test_handle_lookup_error_strict(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "role.yaml",
        """
        roles:
          - model: missing_app.stub
            name: stub
            display_name: Stub
            description: ""
            permissions: []
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )


@pytest.mark.django_db
def test_handle_rejects_non_role_model(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "role.yaml",
        """
        roles:
          - model: core.permission
            name: stub
            display_name: Stub
            description: ""
            permissions: []
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )


@pytest.mark.django_db
def test_handle_missing_permissions_strict(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "roles.yaml",
        """
        roles:
          - model: core.role
            name: missing_perm
            display_name: Missing Perm
            description: ""
            permissions:
              - test.sync_roles.missing
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )


@pytest.mark.django_db
def test_handle_duplicate_roles_strict(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "a.yaml",
        """
        roles:
          - model: core.role
            name: dup
            display_name: Duplicate
            description: ""
            permissions: []
        """,
    )
    write_yaml(
        tmp_path / "b.yaml",
        """
        roles:
          - model: core.role
            name: dup
            display_name: Duplicate
            description: ""
            permissions: []
        """,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_roles",
            str(tmp_path),
            strict=True,
            prune=False,
            dry_run=False,
        )

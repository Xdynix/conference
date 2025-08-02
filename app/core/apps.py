import sys
from typing import TYPE_CHECKING, Any, TextIO

from django.apps import AppConfig
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.db import DEFAULT_DB_ALIAS
from django.db.models.signals import post_migrate

from app.utils.perm import get_perms

if TYPE_CHECKING:
    from app.core.models import Permission


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.core"

    def ready(self) -> None:
        post_migrate.connect(
            create_permissions,
            dispatch_uid="core.app.create_permissions",
        )


def create_permissions(
    app_config: AppConfig,
    verbosity: int = 2,
    using: str = DEFAULT_DB_ALIAS,
    apps: Apps | None = None,
    stdout: TextIO = sys.stdout,
    **_: Any,
) -> None:  # pragma: no cover
    apps = apps or global_apps
    try:
        app_config = apps.get_app_config(app_config.label)
    except LookupError:
        return

    try:
        perm_cls: type[Permission] = apps.get_model("core", "Permission")
    except LookupError:
        if verbosity >= 3:
            print(
                "Skipping creating permissions, "
                "because `core.Permission` model doesn't exist.",
                file=stdout,
            )
        return

    all_perms = set(perm_cls.objects.using(using).values_list("key", flat=True))

    permissions: list[Permission] = []
    for hist_model in app_config.get_models():
        # `app_config.get_models()` returns historical model classes: lightweight,
        # "fake" versions that reflect the schema and Meta options at the time of
        # migration but exclude any custom methods or attributes.
        # Since our `get_perms()` helper relies on scanning the real model class, we
        # fetch it from the global app registry instead.
        hist_model_meta = hist_model._meta
        model = global_apps.get_model(
            hist_model_meta.app_label,
            hist_model_meta.model_name,
        )
        for perm in get_perms(model):
            if perm in all_perms:
                continue
            permissions.append(perm_cls(key=perm))
    perm_cls.objects.using(using).bulk_create(permissions, ignore_conflicts=True)
    # TODO: Check duplicate permission keys.
    # TODO: Check orphaned permissions.

    if verbosity >= 2:
        for permission in permissions:
            print(f"Adding permission {permission.key}.", file=stdout)

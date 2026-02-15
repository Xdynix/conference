from django.contrib import admin
from django.http import HttpRequest

from app.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin[AuditLog]):
    date_hierarchy = "timestamp"
    list_display = (
        "timestamp",
        "action",
        "actor_label",
        "resource",
        "resource_id",
        "scope",
    )
    list_filter = ("action", "resource", "scope")
    search_fields = (
        "actor_uid",
        "actor_label",
        "resource_id",
        "resource_label",
        "request_id",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002
        return False

    def has_change_permission(
        self,
        request: HttpRequest,  # noqa: ARG002
        obj: AuditLog | None = None,  # noqa: ARG002
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,  # noqa: ARG002
        obj: AuditLog | None = None,  # noqa: ARG002
    ) -> bool:
        return False

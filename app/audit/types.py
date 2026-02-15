from enum import StrEnum
from typing import TypedDict


class AuditResource(StrEnum):
    pass


class AuditAction(StrEnum):
    pass


class AuditResourceInfo(TypedDict):
    resource: AuditResource
    resource_id: str
    resource_label: str


class Auditable:
    """Mixin for models that can be referenced in audit log entries.

    Subclasses must implement ``audit_resource_info`` to provide the resource type,
    identifier, and human-readable label for audit logging.
    """

    def audit_resource_info(self) -> AuditResourceInfo:  # pragma: no cover
        """Return audit resource metadata for this instance."""
        raise NotImplementedError

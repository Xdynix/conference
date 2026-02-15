from enum import StrEnum
from typing import TypedDict


class AuditResource(StrEnum):
    SESSION = "session"
    USER = "user"


class AuditAction(StrEnum):
    # Session
    SESSION_CREATE = "session.create"
    SESSION_CREATE_FAILED = "session.create_failed"
    SESSION_DELETE = "session.delete"
    SESSION_ASSUME = "session.assume"
    SESSION_REVERT = "session.revert"

    # User
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_SET_PASSWORD = "user.set_password"  # noqa: S105
    USER_SET_ROLES = "user.set_roles"
    USER_REQUEST_PASSWORD_RESET = "user.request_password_reset"  # noqa: S105
    USER_RESET_PASSWORD = "user.reset_password"  # noqa: S105
    USER_RESET_PASSWORD_FAILED = "user.reset_password_failed"  # noqa: S105


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

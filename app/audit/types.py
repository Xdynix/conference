from enum import StrEnum
from typing import TypedDict


class AuditResource(StrEnum):
    CODE_POOL = "code_pool"
    CONFERENCE = "conference"
    SESSION = "session"
    TRACK = "track"
    USER = "user"


class AuditAction(StrEnum):
    # Code Pool
    CODE_POOL_CREATE = "code_pool.create"
    CODE_POOL_UPDATE = "code_pool.update"
    CODE_POOL_DELETE = "code_pool.delete"
    CODE_POOL_ASSIGN_TRACKS = "code_pool.assign_tracks"

    # Conference
    CONFERENCE_CREATE = "conference.create"
    CONFERENCE_UPDATE = "conference.update"
    CONFERENCE_DELETE = "conference.delete"
    CONFERENCE_UPDATE_ECOPYRIGHT_CONFIG = "conference.update_ecopyright_config"
    CONFERENCE_REFRESH_ECOPYRIGHT_CONSENTS = "conference.refresh_ecopyright_consents"

    # Session
    SESSION_CREATE = "session.create"
    SESSION_CREATE_FAILED = "session.create_failed"
    SESSION_DELETE = "session.delete"
    SESSION_ASSUME = "session.assume"
    SESSION_REVERT = "session.revert"

    # Track
    TRACK_CREATE = "track.create"
    TRACK_UPDATE = "track.update"
    TRACK_DELETE = "track.delete"
    TRACK_REORDER = "track.reorder"

    # User
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_SET_PASSWORD = "user.set_password"  # noqa: S105
    USER_SET_ROLES = "user.set_roles"
    USER_REQUEST_PASSWORD_RESET = "user.request_password_reset"  # noqa: S105
    USER_RESET_PASSWORD = "user.reset_password"  # noqa: S105
    USER_RESET_PASSWORD_FAILED = "user.reset_password_failed"  # noqa: S105
    USER_UPDATE_CONFERENCE_PROFILE = "user.update_conference_profile"
    USER_UPDATE_PROFILE = "user.update_profile"


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

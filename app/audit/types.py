from enum import StrEnum
from typing import TypedDict


class AuditResource(StrEnum):
    ADMIN_COMMENT = "admin_comment"
    ATTENDANCE_TYPE = "attendance_type"
    CODE_POOL = "code_pool"
    CONFERENCE_FILE = "conference_file"
    CONFERENCE = "conference"
    EMAIL_VERIFICATION = "email_verification"
    EMAIL = "email"
    INVITATION = "invitation"
    PAPER = "paper"
    PAYMENT = "payment"
    REGISTRATION = "registration"
    REVIEW = "review"
    SESSION = "session"
    TRACK = "track"
    USER = "user"


class AuditAction(StrEnum):
    # Admin Comment
    ADMIN_COMMENT_CREATE = "admin_comment.create"
    ADMIN_COMMENT_DELETE = "admin_comment.delete"

    # Attendance Type
    ATTENDANCE_TYPE_CREATE = "attendance_type.create"
    ATTENDANCE_TYPE_DELETE = "attendance_type.delete"
    ATTENDANCE_TYPE_REORDER = "attendance_type.reorder"
    ATTENDANCE_TYPE_UPDATE = "attendance_type.update"

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

    # Conference File
    CONFERENCE_FILE_UPLOAD = "conference_file.upload"
    CONFERENCE_FILE_DELETE = "conference_file.delete"

    # Email
    EMAIL_SEND = "email.send"

    # Email Verification
    EMAIL_VERIFICATION_ISSUE_CODE = "email_verification.issue_code"
    EMAIL_VERIFICATION_VERIFY_CODE = "email_verification.verify_code"

    # Invitation
    INVITATION_CREATE = "invitation.create"
    INVITATION_DELETE = "invitation.delete"
    INVITATION_REDEEM = "invitation.redeem"
    INVITATION_REDEEM_FAILED = "invitation.redeem_failed"
    INVITATION_REJECT = "invitation.reject"
    INVITATION_SEND = "invitation.send"
    INVITATION_UPDATE = "invitation.update"

    # Paper
    PAPER_ANNOUNCE = "paper.announce"
    PAPER_CREATE = "paper.create"
    PAPER_DECIDE = "paper.decide"
    PAPER_DELETE = "paper.delete"
    PAPER_GENERATE_ACCEPTANCE_LETTER = "paper.generate_acceptance_letter"
    PAPER_RELOCATE = "paper.relocate"
    PAPER_REMOVE_CLAIM = "paper.remove_claim"
    PAPER_SET_CLAIM = "paper.set_claim"
    PAPER_SET_FINAL_LIMIT = "paper.set_final_limit"
    PAPER_SET_LABELS = "paper.set_labels"
    PAPER_SUBMIT = "paper.submit"
    PAPER_TRANSFER = "paper.transfer"
    PAPER_UNSUBMIT = "paper.unsubmit"
    PAPER_UPDATE = "paper.update"
    PAPER_UPLOAD_FINAL = "paper.upload_final"
    PAPER_UPLOAD_SUBMISSION = "paper.upload_submission"
    PAPER_WITHDRAW = "paper.withdraw"

    # Payment
    PAYMENT_CREATE = "payment.create"
    PAYMENT_DELETE = "payment.delete"
    PAYMENT_UPDATE = "payment.update"

    # Review
    REVIEW_ACCEPT = "review.accept"
    REVIEW_ASSIGN = "review.assign"
    REVIEW_CANCEL = "review.cancel"
    REVIEW_DECLINE = "review.decline"
    REVIEW_IMPORT = "review.import"
    REVIEW_SEND_NOTIFICATIONS = "review.send_notifications"
    REVIEW_SUBMIT = "review.submit"
    REVIEW_UNSUBMIT = "review.unsubmit"
    REVIEW_UPDATE = "review.update"

    # Registration
    REGISTRATION_CANCEL = "registration.cancel"
    REGISTRATION_CREATE = "registration.create"
    REGISTRATION_GENERATE_RECEIPT = "registration.generate_receipt"
    REGISTRATION_UPDATE = "registration.update"

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
    USER_MUTATE_ROLE_ASSIGNMENT = "user.mutate_role_assignment"
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

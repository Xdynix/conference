from enum import StrEnum


class CFTurnstileMode(StrEnum):
    DISABLED = "disabled"
    STRICT = "strict"
    # TODO: Add lenient mode to allow failed verification.

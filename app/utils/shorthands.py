__all__ = (
    "days",
    "parse_durations",
    "sanitize_email_subject",
    "seconds",
    "timedelta_cast",
)

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Literal


def timedelta_cast(
    unit: Literal["milliseconds", "seconds", "minutes", "hours", "days", "weeks"],
) -> Callable[[str | float], timedelta]:
    """Create a casting function that converts strings or floats to timedelta objects.

    Examples:
        >>> minutes = timedelta_cast("minutes")
        >>> minutes("30")
        datetime.timedelta(seconds=1800)
        >>> minutes(45.5)
        datetime.timedelta(seconds=2730)

        >>> hours = timedelta_cast("hours")
        >>> hours("2.5")
        datetime.timedelta(seconds=9000)
    """

    def cast(s: str | float) -> timedelta:
        return timedelta(**{unit: float(s)})  # type: ignore[misc]

    return cast


seconds = timedelta_cast("seconds")
days = timedelta_cast("days")


UNITS_MAP = {
    "s": "seconds",
    "sec": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "min": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
}
DURATION_PATTERN = re.compile(r"^(\d*\.?\d*)?\s*([a-zA-Z]+)$")


def parse_durations(s: str) -> timedelta:
    """Convert human-readable string to a ``timedelta`` object.

    >>> parse_durations("1h")
    datetime.timedelta(seconds=3600)
    >>> parse_durations("s")
    datetime.timedelta(seconds=1)
    >>> parse_durations("1.5 min")
    datetime.timedelta(seconds=90)
    >>> parse_durations("1 2 3")
    Traceback (most recent call last):
     ...
    ValueError: Invalid duration format: 1 2 3
    >>> parse_durations("1 month")
    Traceback (most recent call last):
     ...
    ValueError: Invalid unit: month
    """
    match = DURATION_PATTERN.match(s)
    if not match:
        raise ValueError(f"Invalid duration format: {s}")

    val_str, unit_str = match.groups()
    val = float(val_str) if val_str else 1.0
    if unit_str not in UNITS_MAP:
        raise ValueError(f"Invalid unit: {unit_str}")

    return timedelta(**{UNITS_MAP[unit_str]: val})


def sanitize_email_subject(subject: str) -> str:
    """Remove newlines from email subject to prevent header injection.

    Examples:
        >>> sanitize_email_subject("Hello\\nWorld")
        'HelloWorld'
        >>> sanitize_email_subject("Single line")
        'Single line'
    """
    return "".join(subject.splitlines())

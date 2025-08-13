from collections.abc import Callable
from datetime import timedelta
from typing import Literal


def timedelta_cast(
    unit: Literal["milliseconds", "seconds", "minutes", "hours", "days", "weeks"],
) -> Callable[[str | float], timedelta]:
    """Create a casting function that converts strings or floats to timedelta objects.

    Args:
        unit: The time unit to use for the timedelta conversion.

    Returns:
        A callable that takes a string or float and returns a timedelta object.

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

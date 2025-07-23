from collections.abc import Callable, Iterable, Mapping
from typing import Any

class Job:
    id: str
    name: str
    func: Callable[..., Any]
    args: Iterable[Any]
    kwargs: Mapping[str, Any]

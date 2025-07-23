from collections.abc import Callable
from typing import Any, TypeVar

from apscheduler.events import SchedulerEvent
from apscheduler.job import Job

F = TypeVar("F", bound=Callable[..., Any])

class BaseScheduler:
    def start(self, paused: bool = ...) -> None: ...
    def shutdown(self, wait: bool = ...) -> None: ...
    @property
    def running(self) -> bool: ...
    def add_listener(
        self,
        callback: Callable[[SchedulerEvent], Any],
        mask: int = ...,
    ) -> None: ...
    def scheduled_job(self, *args: Any, **kwargs: Any) -> Callable[[F], F]: ...
    def get_jobs(self, jobstore: str | None = ...) -> list[Job]: ...

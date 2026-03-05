"""Shared background scheduler for the application.

The ``scheduler`` instance is the single APScheduler ``BackgroundScheduler`` used across
the project. Apps register periodic jobs by defining a ``jobs.py`` module that imports
``scheduler`` and decorates functions with ``@scheduler.scheduled_job(...)``. The
``runscheduler`` management command auto-discovers these modules at startup by importing
``<app>.jobs`` for every installed application.

See ``app/infra/management/commands/runscheduler.py`` for the discovery logic and any
existing ``jobs.py`` (e.g. ``app/infra/jobs.py``) for the registration pattern.
"""

__all__ = ("scheduler",)

from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from django.db import close_old_connections as django_close_old_connections

# The scheduler instance shared by the entire project.
scheduler = BackgroundScheduler()


def close_old_connections(_: Any) -> None:  # pragma: no cover
    """APScheduler event listener that invokes ``close_old_connections``."""
    # Django will manage database connections within its request-response cycle. But
    # outside of that, such as in a long-running process, we need to close old
    # connections ourselves.
    django_close_old_connections()


scheduler.add_listener(close_old_connections, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

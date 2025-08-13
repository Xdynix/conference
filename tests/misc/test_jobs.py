from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.sessions.management.commands.clearsessions import (
    Command as ClearSessionsCommand,
)
from django.core.management import BaseCommand
from mailer.management.commands.purge_mail_log import (  # type: ignore[import-untyped]
    Command as PurgeMailLogCommand,
)
from mailer.management.commands.retry_deferred import (  # type: ignore[import-untyped]
    Command as RetryDeferredCommand,
)
from pytest_mock import MockerFixture

from app.infra.services import scheduler
from app.misc import jobs


@pytest.mark.parametrize(
    "job_func",
    [
        jobs.clear_sessions,
        jobs.retry_deferred,
        jobs.purge_mail_log,
    ],
)
def test_job_scheduled(job_func: Callable[..., Any]) -> None:
    assert sum(job.func is job_func for job in scheduler.get_jobs()) == 1


@pytest.mark.parametrize(
    "job_func, command",
    [
        (jobs.clear_sessions, ClearSessionsCommand),
        (jobs.retry_deferred, RetryDeferredCommand),
        (jobs.purge_mail_log, PurgeMailLogCommand),
    ],
)
def test_call_command_jobs(
    mocker: MockerFixture,
    job_func: Callable[..., Any],
    command: type[BaseCommand],
) -> None:
    execute = mocker.patch.object(command, "execute")

    job_func()

    execute.assert_called_once()

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.management.commands.clearsessions import (
    Command as ClearSessionsCommand,
)
from pytest_mock import MockerFixture

from app.infra.services import scheduler
from app.misc import jobs


@pytest.mark.parametrize("job_func", [jobs.clear_sessions, jobs.check_disk_usage])
def test_job_scheduled(job_func: Callable[..., Any]) -> None:
    assert sum(job.func is job_func for job in scheduler.get_jobs()) == 1


def test_clear_sessions(mocker: MockerFixture) -> None:
    execute = mocker.patch.object(ClearSessionsCommand, "execute")

    jobs.clear_sessions()

    execute.assert_called_once()


GB = 1024**3


def test_check_disk_usage_above_threshold(
    mocker: MockerFixture,
    settings: LazySettings,
) -> None:
    settings.DISK_FREE_THRESHOLD = 2.0
    mock_usage = mocker.patch(
        "app.misc.jobs.shutil.disk_usage",
        return_value=SimpleNamespace(total=100 * GB, used=80 * GB, free=20 * GB),
    )
    mock_error = mocker.patch("app.misc.jobs.logger.error")

    jobs.check_disk_usage()

    mock_usage.assert_called_once_with(settings.DATA_DIR)
    mock_error.assert_not_called()


def test_check_disk_usage_below_threshold(
    mocker: MockerFixture,
    settings: LazySettings,
) -> None:
    settings.DISK_FREE_THRESHOLD = 2.0
    mocker.patch(
        "app.misc.jobs.shutil.disk_usage",
        return_value=SimpleNamespace(total=100 * GB, used=99 * GB, free=1 * GB),
    )
    mock_error = mocker.patch("app.misc.jobs.logger.error")

    jobs.check_disk_usage()

    mock_error.assert_called_once_with(
        "Free disk space below threshold.",
        free_gb=1.0,
        total_gb=100.0,
        threshold_gb=2.0,
    )


def test_check_disk_usage_at_exact_threshold(
    mocker: MockerFixture,
    settings: LazySettings,
) -> None:
    settings.DISK_FREE_THRESHOLD = 2.0
    mocker.patch(
        "app.misc.jobs.shutil.disk_usage",
        return_value=SimpleNamespace(total=100 * GB, used=98 * GB, free=2 * GB),
    )
    mock_error = mocker.patch("app.misc.jobs.logger.error")

    jobs.check_disk_usage()

    mock_error.assert_not_called()

from unittest.mock import MagicMock

from django.conf import LazySettings
from pytest_mock import MockerFixture

from app.conference import jobs
from app.infra.services import scheduler


def test_job_scheduled() -> None:
    assert sum(job.func is jobs.duplicate_scan for job in scheduler.get_jobs()) == 1


def test_duplicate_scan_calls_service(
    mocker: MockerFixture,
    settings: LazySettings,
) -> None:
    report = MagicMock()
    scan = mocker.patch(
        "app.conference.jobs.DuplicateService.scan",
        return_value=report,
    )
    mocker.patch("app.conference.jobs.logger.info")

    jobs.duplicate_scan()

    scan.assert_called_once_with(
        scan_window=settings.DUPLICATE_SCAN_WINDOW,
        paper_count_cap=settings.DUPLICATE_PAPER_COUNT_CAP,
        title_similarity_threshold=settings.DUPLICATE_TITLE_SIMILARITY_THRESHOLD,
        retention_successful=settings.DUPLICATE_RETENTION_SUCCESSFUL,
        retention_failed=settings.DUPLICATE_RETENTION_FAILED,
    )


def test_duplicate_scan_logs_on_report(mocker: MockerFixture) -> None:
    report = MagicMock()
    mocker.patch(
        "app.conference.jobs.DuplicateService.scan",
        return_value=report,
    )
    mock_info = mocker.patch("app.conference.jobs.logger.info")

    jobs.duplicate_scan()

    mock_info.assert_called_once_with(
        "Duplicate scan completed.",
        report_id=report.pk,
        state=report.state,
    )


def test_duplicate_scan_skips_logging_when_no_report(mocker: MockerFixture) -> None:
    mocker.patch(
        "app.conference.jobs.DuplicateService.scan",
        return_value=None,
    )
    mock_info = mocker.patch("app.conference.jobs.logger.info")

    jobs.duplicate_scan()

    mock_info.assert_not_called()

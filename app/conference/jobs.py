from django.conf import settings
from loguru import logger

from app.conference.services.duplicate import DuplicateService
from app.infra.services import scheduler


@scheduler.scheduled_job("interval", minutes=2, jitter=30)
def duplicate_scan() -> None:
    report = DuplicateService.scan(
        scan_window=settings.DUPLICATE_SCAN_WINDOW,
        paper_count_cap=settings.DUPLICATE_PAPER_COUNT_CAP,
        title_similarity_threshold=settings.DUPLICATE_TITLE_SIMILARITY_THRESHOLD,
        retention_successful=settings.DUPLICATE_RETENTION_SUCCESSFUL,
        retention_failed=settings.DUPLICATE_RETENTION_FAILED,
    )
    if report is None:
        return

    logger.info("Duplicate scan completed.", report_id=report.pk, state=report.state)

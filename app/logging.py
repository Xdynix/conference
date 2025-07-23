"""Logging configurations.

This module is imported while Django settings are being configured, before Django is
fully initialized.
"""

import inspect
import logging
import sys
from pathlib import Path
from typing import NamedTuple

from loguru import logger


# Intercept standard logging messages to Loguru.
# Ref: https://github.com/Delgan/loguru#entirely-compatible-with-standard-logging
class InterceptHandler(logging.Handler):  # pragma: no cover
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


class Handlers(NamedTuple):
    console_logger: int
    file_logger: int


def configure_logging(log_dir: Path, debug: bool) -> Handlers:
    # Route built-in logging to Loguru.
    intercept_handler = InterceptHandler()
    logging.basicConfig(handlers=[intercept_handler], level=logging.NOTSET, force=True)

    logger.remove()  # Remove Loguru default sink (STDERR).

    log_format = (
        # Adapted from `loguru._defaults.LOGURU_FORMAT` with the addition of `extra`.
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level> <i>extra={extra}</i>"
    )
    level_per_module: dict[str | None, str | int | bool] = {
        "": "INFO",
        "app": "DEBUG" if debug else "INFO",
    }

    console_logger = logger.add(
        sys.stderr,
        format=log_format,
        filter=level_per_module,
        diagnose=debug,
    )
    file_logger = logger.add(
        log_dir / "{time:YYYY-MM-DD}.log",
        format=log_format,
        filter=level_per_module,
        colorize=False,
        diagnose=debug,
        rotation="1 day",
        retention="2 months",
        enqueue=True,
    )
    # TODO: Integrate Sentry.
    return Handlers(console_logger=console_logger, file_logger=file_logger)

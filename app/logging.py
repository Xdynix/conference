"""Logging configurations.

This module is imported while Django settings are being configured, before Django is
fully initialized.
"""

__all__ = ("configure_logging",)

import inspect
import logging
import sys
from pathlib import Path

import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.types import Event, Hint

# Library logs route through stdlib into Loguru, so setting their level here drops
# records at the source; the mute then applies to every sink, local and Sentry alike.
LIBRARY_LOG_LEVELS: dict[str, int] = {
    "httpx": logging.WARNING,
    "apscheduler.executors": logging.WARNING,
}


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


def sentry_before_send(event: Event, hint: Hint) -> Event | None:  # pragma: no cover
    """Filter out events that should not be sent to Sentry."""
    # Ignore KeyboardInterrupt used to stop the server.
    if "exc_info" in hint:
        _, exc_value, _ = hint["exc_info"]
        if isinstance(exc_value, KeyboardInterrupt):
            return None
    # Django's `log_response` logs all 4xx/5xx via the `django.request` stdlib logger,
    # which duplicates events already captured by the application error handler.
    if event.get("logger") == "django.utils.log":
        return None
    return event


def traces_sampler(sampling_context: dict[str, object]) -> float:  # pragma: no cover
    """Drop traces for health checks and static file serving."""
    from django.conf import settings

    asgi_scope = sampling_context.get("asgi_scope")
    wsgi_environ = sampling_context.get("wsgi_environ")
    if isinstance(asgi_scope, dict):
        path = asgi_scope.get("path", "")
        # ASGI path includes the full URL; strip the subpath prefix if present.
        prefix = settings.FORCE_SCRIPT_NAME or ""
        if prefix:
            path = path.removeprefix(prefix) or "/"
    elif isinstance(wsgi_environ, dict):
        # WSGI PATH_INFO is already app-relative.
        path = wsgi_environ.get("PATH_INFO", "")
    else:
        return 1.0

    static_url = settings.STATIC_URL.removeprefix(settings.FORCE_SCRIPT_NAME or "")
    if path == "/api/health-status" or path.startswith(static_url):
        return 0
    return 1.0


def configure_logging(
    log_dir: Path | None,
    debug: bool,
    sentry_dsn: str = "",
) -> None:  # pragma: no cover
    # Route built-in logging to Loguru.
    intercept_handler = InterceptHandler()
    logging.basicConfig(handlers=[intercept_handler], level=logging.NOTSET, force=True)

    for logger_name, log_level in LIBRARY_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(log_level)

    logger.remove()  # Remove Loguru default sink (STDERR).

    log_format = (
        # Adapted from `loguru._defaults.LOGURU_FORMAT` with the addition of `extra`.
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level> <i>extra={extra}</i>"
    )
    # Governs only Loguru's own sinks (stderr, file). Library mutes belong in
    # LIBRARY_LOG_LEVELS so they also reach Sentry; adding one here would leak to it.
    level_per_module: dict[str | None, str | int | bool] = {
        "": "INFO",
        "app": "DEBUG" if debug else "INFO",
    }

    logger.add(
        sys.stderr,
        format=log_format,
        filter=level_per_module,
        diagnose=debug,
    )

    if log_dir is not None:
        logger.add(
            log_dir / "{time:YYYY-MM-DD}.log",
            format=log_format,
            filter=level_per_module,
            colorize=False,
            diagnose=debug,
            rotation="1 day",
            retention="2 months",
            enqueue=True,
        )

    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                # Use a format function (not a string) so loguru does not append the
                # exception traceback to the message; Sentry captures it separately
                # via the structured exception data.
                LoguruIntegration(
                    event_format=lambda _: "{message}",
                    breadcrumb_format=lambda _: "{message}",
                ),
            ],
            # Fully disable `LoggingIntegration` to prevent it from monkey-patching
            # stdlib `callHandlers`. The `LoguruIntegration` above handles event capture
            # through `loguru`, and the `InterceptHandler` routes all stdlib logging
            # there.
            disabled_integrations=[LoggingIntegration()],
            before_send=sentry_before_send,
            enable_logs=True,
            environment="development" if debug else "production",
            send_default_pii=False,
            traces_sampler=traces_sampler,
        )

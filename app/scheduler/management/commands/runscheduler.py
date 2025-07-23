import importlib
import signal
from argparse import ArgumentParser
from contextlib import suppress
from threading import Event
from typing import Any

from django.apps import apps
from django.core.management import BaseCommand

from app.scheduler.core import scheduler


class Command(BaseCommand):
    help = "Start a long-running worker to execute the scheduled jobs."

    # Each app should define their jobs in `app.jobs` module.
    jobs_module_name = ".jobs"
    stop_event = Event()

    def add_arguments(self, parser: ArgumentParser) -> None:  # pragma: no cover
        parser.add_argument(
            "-m",
            "--module",
            default=self.jobs_module_name,
            help=(
                "Specifies the relative path used to search for scheduled tasks "
                f"within installed applications. Default: `{self.jobs_module_name}`."
            ),
        )

    def handle(self, *_: Any, module: str = jobs_module_name, **__: Any) -> None:
        self.start_scheduler()
        self.load_jobs(module)
        self.register_shutdown()
        self.run_until_stopped()

    @classmethod
    def start_scheduler(cls) -> None:
        scheduler.start()

    @classmethod
    def load_jobs(cls, module: str = jobs_module_name) -> None:
        for app_config in apps.get_app_configs():
            with suppress(ModuleNotFoundError):
                importlib.import_module(module, app_config.name)

    def register_shutdown(self) -> None:  # pragma: no cover
        def shutdown(*_: Any) -> None:
            """Shutdown the scheduler gracefully."""
            if scheduler.running:
                scheduler.shutdown()
            self.stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, shutdown)

    def run_until_stopped(self) -> None:  # pragma: no cover
        while not self.stop_event.wait(0.1):
            pass

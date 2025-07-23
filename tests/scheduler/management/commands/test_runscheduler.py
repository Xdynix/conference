import importlib
from unittest.mock import call

import pytest
from django.apps import apps
from faker import Faker
from pytest_mock import MockerFixture

from app.scheduler.core import scheduler
from app.scheduler.management.commands.runscheduler import Command


@pytest.fixture
def command() -> Command:
    return Command()


def test_handle(mocker: MockerFixture, command: Command) -> None:
    start_scheduler = mocker.patch.object(command, "start_scheduler")
    load_jobs = mocker.patch.object(command, "load_jobs")
    register_shutdown = mocker.patch.object(command, "register_shutdown")
    run_until_stopped = mocker.patch.object(command, "run_until_stopped")

    command.handle()

    start_scheduler.assert_called_once_with()
    load_jobs.assert_called_once_with(command.jobs_module_name)
    register_shutdown.assert_called_once_with()
    run_until_stopped.assert_called_once_with()


def test_start_scheduler(mocker: MockerFixture, command: Command) -> None:
    start = mocker.patch.object(scheduler, "start")

    command.start_scheduler()

    start.assert_called_once_with()


def test_load_jobs(mocker: MockerFixture, faker: Faker, command: Command) -> None:
    app_configs = [mocker.Mock(name=faker.pystr()) for _ in range(5)]
    get_app_configs = mocker.patch.object(
        apps,
        "get_app_configs",
        return_value=app_configs,
    )
    import_module = mocker.patch.object(importlib, "import_module")

    command.load_jobs()

    get_app_configs.assert_called_once_with()
    assert import_module.call_args_list == [
        call(command.jobs_module_name, app_config.name) for app_config in app_configs
    ]


def test_load_jobs_module_not_found(
    mocker: MockerFixture,
    faker: Faker,
    command: Command,
) -> None:
    mocker.patch.object(
        apps,
        "get_app_configs",
        return_value=[mocker.Mock(name=faker.pystr())],
    )
    mocker.patch.object(
        importlib,
        "import_module",
        side_effect=ModuleNotFoundError,
    )

    command.load_jobs()

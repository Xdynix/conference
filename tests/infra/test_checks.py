from collections.abc import Callable, Mapping
from types import SimpleNamespace

import pytest
from django.core.checks import run_checks
from django.db import connections
from pytest_mock import MockerFixture

type RunCheck = Callable[..., list[str | None]]


def connection_stub(
    options: Mapping[str, object],
    *,
    vendor: str = "sqlite",
    alias: str = "default",
) -> SimpleNamespace:
    return SimpleNamespace(
        vendor=vendor, alias=alias, settings_dict={"OPTIONS": options}
    )


@pytest.fixture
def run_check(mocker: MockerFixture) -> RunCheck:
    def run(*stubs: SimpleNamespace) -> list[str | None]:
        mocker.patch.object(connections, "all", return_value=list(stubs))
        return [message.id for message in run_checks(tags=["infra"])]

    return run


def test_happy_path(run_check: RunCheck) -> None:
    assert run_check(connection_stub({"transaction_mode": "IMMEDIATE"})) == []


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"transaction_mode": "DEFERRED"}, id="DEFERRED"),
        pytest.param({"transaction_mode": "deferred"}, id="deferred"),
        pytest.param({"transaction_mode": None}, id="none"),
        pytest.param({}, id="unset"),
    ],
)
def test_rejects_deferred(run_check: RunCheck, options: dict[str, str | None]) -> None:
    assert run_check(connection_stub(options)) == ["infra.E001"]


@pytest.mark.parametrize("mode", ["IMMEDIATE", "immediate", "EXCLUSIVE"])
def test_accepts_write_first_modes(run_check: RunCheck, mode: str) -> None:
    assert run_check(connection_stub({"transaction_mode": mode})) == []


def test_ignores_other_vendors(run_check: RunCheck) -> None:
    assert run_check(connection_stub({}, vendor="postgresql")) == []


def test_reports_each_sqlite_alias(run_check: RunCheck) -> None:
    stubs = (
        connection_stub({"transaction_mode": "IMMEDIATE"}, alias="good"),
        connection_stub({}, alias="bad"),
        connection_stub({"transaction_mode": "deferred"}, alias="worse"),
    )
    assert run_check(*stubs) == ["infra.E001", "infra.E001"]

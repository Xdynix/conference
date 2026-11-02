from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import LazySettings
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


class TestSqliteTransactionMode:
    @pytest.fixture
    def run_check(self, mocker: MockerFixture) -> RunCheck:
        def run(*stubs: SimpleNamespace) -> list[str | None]:
            mocker.patch.object(connections, "all", return_value=list(stubs))
            return [message.id for message in run_checks(tags=["infra"])]

        return run

    def test_happy_path(self, run_check: RunCheck) -> None:
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
    def test_rejects_deferred(
        self,
        run_check: RunCheck,
        options: dict[str, str | None],
    ) -> None:
        assert run_check(connection_stub(options)) == ["infra.E001"]

    @pytest.mark.parametrize("mode", ["IMMEDIATE", "immediate", "EXCLUSIVE"])
    def test_accepts_write_first_modes(self, run_check: RunCheck, mode: str) -> None:
        assert run_check(connection_stub({"transaction_mode": mode})) == []

    def test_ignores_other_vendors(self, run_check: RunCheck) -> None:
        assert run_check(connection_stub({}, vendor="postgresql")) == []

    def test_reports_each_sqlite_alias(self, run_check: RunCheck) -> None:
        stubs = (
            connection_stub({"transaction_mode": "IMMEDIATE"}, alias="good"),
            connection_stub({}, alias="bad"),
            connection_stub({"transaction_mode": "deferred"}, alias="worse"),
        )
        assert run_check(*stubs) == ["infra.E001", "infra.E001"]


SMTP = "django.core.mail.backends.smtp.EmailBackend"
QUEUE = "app.infra.mail.EmailBackend"


class TestDeliveryMailer:
    @pytest.fixture
    def run_check(self, settings: LazySettings) -> RunCheck:
        def run(
            delivery: dict[str, Any],
            *,
            default_mailer: str = "delivery",
        ) -> list[str | None]:
            settings.MAILERS = {"default": {"BACKEND": QUEUE}, "delivery": delivery}
            settings.POST_OFFICE = {
                **settings.POST_OFFICE,
                "DEFAULT_MAILER": default_mailer,
            }
            messages = run_checks(tags=["infra"], include_deployment_checks=True)
            return [message.id for message in messages]

        return run

    def test_smtp_passes(self, run_check: RunCheck) -> None:
        delivery = {"BACKEND": SMTP, "OPTIONS": {"host": "smtp.example.com"}}
        assert run_check(delivery) == []

    @pytest.mark.parametrize(
        "backend",
        [
            "django.core.mail.backends.filebased.EmailBackend",
            "django.core.mail.backends.console.EmailBackend",
        ],
    )
    def test_rejects_development_backends(
        self,
        run_check: RunCheck,
        backend: str,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        options = (
            {"file_path": tmp_path_factory.mktemp("emails")}
            if "filebased" in backend
            else {}
        )
        assert run_check({"BACKEND": backend, "OPTIONS": options}) == ["infra.E004"]

    def test_rejects_missing_alias(self, run_check: RunCheck) -> None:
        delivery = {"BACKEND": SMTP, "OPTIONS": {"host": "smtp.example.com"}}
        assert run_check(delivery, default_mailer="nope") == ["infra.E002"]

    def test_rejects_bad_backend(self, run_check: RunCheck) -> None:
        assert run_check({"BACKEND": "no.such.Backend"}) == ["infra.E002"]

    def test_rejects_queue_as_transport(self, run_check: RunCheck) -> None:
        delivery = {"BACKEND": SMTP, "OPTIONS": {"host": "smtp.example.com"}}
        assert run_check(delivery, default_mailer="default") == ["infra.E003"]

    def test_is_deploy_only(self, settings: LazySettings) -> None:
        settings.MAILERS = {
            "default": {"BACKEND": QUEUE},
            "delivery": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
        }
        assert [message.id for message in run_checks(tags=["infra"])] == []


class TestDefaultFromEmail:
    @pytest.fixture
    def run_check(self, settings: LazySettings) -> RunCheck:
        def run(address: str) -> list[str | None]:
            settings.DEFAULT_FROM_EMAIL = address
            return [message.id for message in run_checks(tags=["infra"])]

        return run

    @pytest.mark.parametrize(
        "address",
        ["no-reply@example.com", "Conference <no-reply@example.com>"],
    )
    def test_accepts_bare_and_named_addresses(
        self,
        run_check: RunCheck,
        address: str,
    ) -> None:
        assert run_check(address) == []

    @pytest.mark.parametrize(
        "address",
        [
            pytest.param("no-reply@example", id="no_dot"),
            pytest.param("Conference no-reply@example.com", id="name_without_brackets"),
            pytest.param("a" * 250 + "@example.com", id="too_long"),
        ],
    )
    def test_rejects_unusable_addresses(
        self, run_check: RunCheck, address: str
    ) -> None:
        assert run_check(address) == ["infra.E005"]

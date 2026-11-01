from collections.abc import Iterable
from typing import Any

from django.core.checks import CheckMessage, Error
from django.db import connections


def check_sqlite_transaction_mode(**kwargs: Any) -> Iterable[CheckMessage]:  # noqa: ARG001
    """Require SQLite aliases to take the write lock at ``BEGIN``.

    SQLite does not wait when a transaction that has already read tries to write
    while another connection holds the write lock; it fails at once with "database is
    locked". In the default DEFERRED mode that breaks a read-then-write transaction
    under concurrency, including a nested ``Mutex.lock_in_transaction``. IMMEDIATE and
    EXCLUSIVE take the lock up front, where SQLite does wait.
    """
    errors: list[CheckMessage] = []
    for connection in connections.all(initialized_only=False):
        if connection.vendor != "sqlite":
            continue
        mode = connection.settings_dict["OPTIONS"].get("transaction_mode") or "DEFERRED"
        if mode.upper() not in {"IMMEDIATE", "EXCLUSIVE"}:
            errors.append(
                Error(
                    f"Database {connection.alias!r} uses SQLite with transaction_mode "
                    f"{mode!r}, so concurrent read-then-write transactions fail "
                    "immediately instead of waiting.",
                    hint="Set OPTIONS['transaction_mode'] to 'IMMEDIATE'.",
                    id="infra.E001",
                )
            )
    return errors

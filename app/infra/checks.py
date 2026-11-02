from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, register
from django.core.checks.mail import NON_PRODUCTION_EMAIL_BACKENDS
from django.core.exceptions import ValidationError
from django.core.mail import InvalidMailer, MailerDoesNotExist, mailers
from django.db import connections
from post_office.backends import EmailBackend as PostOfficeEmailBackend
from post_office.settings import get_default_mailer
from post_office.validators import validate_email_with_name

from app.utils.email import MAX_FROM_EMAIL_LENGTH


@register("infra")
def check_sqlite_transaction_mode(**__: Any) -> Iterable[CheckMessage]:
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


@register("infra", deploy=True)
def check_delivery_mailer(**__: Any) -> Iterable[CheckMessage]:
    """Require a production-ready transport behind the queue.

    Django's ``mail.E001`` inspects only ``MAILERS["default"]``, which is the queue
    here, so the transport behind it needs its own check.
    """
    alias = get_default_mailer()
    try:
        backend = mailers[alias]
    except (MailerDoesNotExist, InvalidMailer) as exc:
        return [
            Error(
                f"The delivery mailer {alias!r} cannot be set up: {exc}",
                hint="Fix MAILERS or POST_OFFICE['DEFAULT_MAILER'].",
                id="infra.E002",
            )
        ]
    if isinstance(backend, PostOfficeEmailBackend):
        return [
            Error(
                f"The delivery mailer {alias!r} is the queue itself, so nothing would "
                "ever be sent.",
                hint="Point POST_OFFICE['DEFAULT_MAILER'] at a transport mailer.",
                id="infra.E003",
            )
        ]
    backend_path = f"{type(backend).__module__}.{type(backend).__qualname__}"
    if backend_path in NON_PRODUCTION_EMAIL_BACKENDS:
        return [
            Error(
                f"The delivery mailer {alias!r} uses a development-only email backend "
                f"({backend_path}).",
                hint="Set EMAIL_BACKEND to the SMTP backend or leave it unset.",
                id="infra.E004",
            )
        ]
    return []


@register("infra")
def check_default_from_email(**__: Any) -> Iterable[CheckMessage]:
    """Reject a ``DEFAULT_FROM_EMAIL`` the queue would refuse on every send."""
    address = settings.DEFAULT_FROM_EMAIL
    try:
        validate_email_with_name(address)
    except ValidationError as exc:
        reason = exc.messages[0]
    else:
        if len(address) <= MAX_FROM_EMAIL_LENGTH:
            return []
        reason = f"It exceeds {MAX_FROM_EMAIL_LENGTH} characters."
    return [
        Error(
            f"DEFAULT_FROM_EMAIL {address!r} is not a usable sender address. {reason}",
            hint='Use a bare address or "Name <address>".',
            id="infra.E005",
        )
    ]

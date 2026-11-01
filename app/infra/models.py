from collections.abc import Generator
from contextlib import contextmanager
from hashlib import sha256

from django.db import models, transaction
from django.db.models.functions import Now
from django.utils.translation import gettext_lazy as _


class Mutex(models.Model):
    """A database-backed distributed mutex.

    On PostgreSQL the lock is per key, so only callers of the same key wait. On SQLite
    it is the database write lock, so every writer waits, and transactions must take
    that lock at ``BEGIN``; ``check_sqlite_transaction_mode`` explains why. Contention
    waits on PostgreSQL and raises ``OperationalError`` on SQLite once the connection
    ``timeout`` elapses.
    """

    key_hash = models.CharField(_("key hash"), max_length=64, primary_key=True)
    touch_time = models.DateTimeField(_("touch time"), db_default=Now())

    class Meta:
        verbose_name = _("mutex")
        verbose_name_plural = _("mutexes")
        indexes = (models.Index(fields=("touch_time",)),)

    def __str__(self) -> str:
        return self.key_hash

    @classmethod
    @contextmanager
    def lock_in_transaction(
        cls,
        key: str,
        *,
        namespace: str = "",
        using: str | None = None,
    ) -> Generator[None]:
        """Acquire a lock for ``namespace`` + ``key`` and hold it for the transaction.

        Joins the current transaction or opens one, and holds the lock until the
        outermost transaction ends. Re-entrant within a transaction: reacquiring the
        same key does not deadlock. Acquire different keys in a consistent order.

        Examples::

            with Mutex.lock_in_transaction(str(resource_id), namespace="resource"):
                resource = Resource.objects.get(pk=resource_id)
                ...
        """
        key_raw = sha256(namespace.encode()).digest() + sha256(key.encode()).digest()
        key_hash = sha256(key_raw).hexdigest()

        features = transaction.get_connection(using).features
        with transaction.atomic(using=using):
            # The upsert is the lock: the row lock on PostgreSQL, the database write
            # lock on SQLite.
            cls.objects.using(using).bulk_create(
                [cls(key_hash=key_hash, touch_time=Now())],  # type: ignore[list-item]
                update_conflicts=True,
                update_fields=["touch_time"],
                unique_fields=(
                    ["key_hash"]
                    if features.supports_update_conflicts_with_target
                    else None
                ),
            )
            yield

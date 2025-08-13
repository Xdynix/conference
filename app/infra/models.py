from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256

from django.db import models, transaction
from django.db.models.functions import Now
from django.utils.translation import gettext_lazy as _


class Mutex(models.Model):
    """A database-backed distributed mutex.

    Stores one row per logical lock key and uses the database to coordinate mutual
    exclusion across processes and machines. On databases that support row-level locks (
    e.g., PostgreSQL, MySQL/InnoDB), it uses ``SELECT ... FOR UPDATE``. On SQLite, it
    relies on a write transaction, which serializes writers for the duration of the
    transaction.
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
    ) -> Iterator[None]:
        """Acquire a lock for ``namespace`` + ``key`` and hold it for the transaction.

        Opens a database transaction, acquires an exclusive lock on the given key, and
        holds it until the transaction ends. The lock remains held until the
        **outermost** transaction ends.

        This function is re-entrant within the same transaction, reacquiring the same
        key won't deadlock. When acquiring multiple different keys, ensure a consistent
        ordering to avoid deadlocks.

        Args:
            key: The logical key to lock on (arbitrary string).
            namespace: Optional namespace to avoid collisions across components.
            using:  Optional Django DB alias.

        Examples::

            with Mutex.lock_in_transaction("user_profile_123", namespace="updates"):
                user.profile.update(data)
        """
        key_raw = sha256(namespace.encode()).digest() + sha256(key.encode()).digest()
        key_hash = sha256(key_raw).hexdigest()

        qs = cls.objects.using(using)
        with transaction.atomic(using=using):
            # Ensure the row exists and "touch" it atomically (upsert).
            # On SQLite this initiates a write transaction, serializing other writers.
            qs.bulk_create(
                [cls(key_hash=key_hash, touch_time=Now())],  # type: ignore[list-item]
                update_conflicts=True,
                update_fields=["touch_time"],
                unique_fields=["key_hash"],
            )
            # Lock the row for the remainder of the transaction (no-op on SQLite).
            qs.select_for_update().only("key_hash").get(key_hash=key_hash)
            yield

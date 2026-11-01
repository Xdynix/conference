from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone
from faker import Faker

from app.infra.models import Mutex


@pytest.mark.django_db
class TestMutex:
    def test_str(self, faker: Faker) -> None:
        mutex = Mutex(key_hash=faker.sha256())
        assert str(mutex) == mutex.key_hash

    def test_same_inputs_share_one_row(self) -> None:
        with Mutex.lock_in_transaction("key", namespace="ns"):
            pass
        with Mutex.lock_in_transaction("key", namespace="ns"):
            pass
        assert Mutex.objects.count() == 1

    def test_namespace_separates_keys(self) -> None:
        with Mutex.lock_in_transaction("key", namespace="ns1"):
            pass
        with Mutex.lock_in_transaction("key", namespace="ns2"):
            pass
        assert Mutex.objects.count() == 2

    def test_namespace_key_boundary_separates_locks(self) -> None:
        with Mutex.lock_in_transaction("c", namespace="ab"):
            pass
        with Mutex.lock_in_transaction("bc", namespace="a"):
            pass
        assert Mutex.objects.count() == 2

    def test_reentrant_in_same_transaction(self) -> None:
        with Mutex.lock_in_transaction("key"), Mutex.lock_in_transaction("key"):
            pass
        assert Mutex.objects.count() == 1

    def test_joins_outer_transaction_after_reads(self) -> None:
        with transaction.atomic():
            assert not Mutex.objects.exists()
            with Mutex.lock_in_transaction("key"):
                assert Mutex.objects.count() == 1
        assert Mutex.objects.count() == 1

    def test_reacquire_touches_row(self) -> None:
        with Mutex.lock_in_transaction("key"):
            pass
        backdated_time = timezone.now() - timedelta(hours=1)
        Mutex.objects.update(touch_time=backdated_time)

        with Mutex.lock_in_transaction("key"):
            pass
        assert Mutex.objects.get().touch_time > backdated_time

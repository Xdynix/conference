from datetime import timedelta

import pytest
from django.utils import timezone
from faker import Faker

from app.infra.models import Mutex


@pytest.mark.django_db
class TestMutex:
    def test_str(self, faker: Faker) -> None:
        key_lock = Mutex(key_hash=faker.sha256())
        assert str(key_lock) == key_lock.key_hash

    def test_deterministic(self) -> None:
        with Mutex.lock_in_transaction("key"):
            pass
        with Mutex.lock_in_transaction("key"):
            pass
        with Mutex.lock_in_transaction("key2"):
            pass
        assert Mutex.objects.count() == 2

    def test_namespaced(self) -> None:
        with Mutex.lock_in_transaction("key"):
            pass
        with Mutex.lock_in_transaction("key", namespace="ns1"):
            pass
        with Mutex.lock_in_transaction("key", namespace="ns2"):
            pass
        assert Mutex.objects.count() == 3

    def test_nested(self) -> None:
        with Mutex.lock_in_transaction("key"), Mutex.lock_in_transaction("key"):
            pass
        assert Mutex.objects.count() == 1

    def test_touch_time_update(self) -> None:
        with Mutex.lock_in_transaction("key"):
            pass

        backdated_time = timezone.now() - timedelta(hours=1)
        Mutex.objects.update(touch_time=backdated_time)

        with Mutex.lock_in_transaction("key"):
            pass

        assert Mutex.objects.get().touch_time > backdated_time

import time

import pytest
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

        key_lock = Mutex.objects.all()[0]
        touch_time = key_lock.touch_time
        time.sleep(0.01)

        with Mutex.lock_in_transaction("key"):
            pass

        key_lock.refresh_from_db()
        assert touch_time < key_lock.touch_time

from datetime import timedelta

import pytest
from django.utils import timezone

from app.core.models import ApiKey, User
from app.core.services import ApiKeyService
from tests.helpers import approx_now, update_object


@pytest.mark.django_db
class TestCreateKey:
    def test_returns_prefixed_plaintext(self, user: User) -> None:
        _, plaintext = ApiKeyService.create_key(user)

        assert plaintext.startswith(ApiKey.KEY_PREFIX)
        assert len(plaintext) > len(ApiKey.KEY_PREFIX)

    def test_stores_hashed_key(self, user: User) -> None:
        api_key, plaintext = ApiKeyService.create_key(user)

        assert api_key.hashed_key == ApiKeyService._hash_key(plaintext)
        assert api_key.hashed_key != plaintext

    def test_stores_auth_hash_snapshot(self, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        assert api_key.auth_hash == user.get_session_auth_hash()

    def test_revokes_existing_key_on_rotation(self, user: User) -> None:
        first_key, first_plaintext = ApiKeyService.create_key(user)

        _, second_plaintext = ApiKeyService.create_key(user)

        first_key.refresh_from_db()
        assert first_key.revoke_time is not None
        assert first_plaintext != second_plaintext

        active_keys = user.api_keys.filter(revoke_time__isnull=True)
        assert active_keys.count() == 1

    def test_multiple_rotations_preserve_old_revoked_keys(self, user: User) -> None:
        first_key, _ = ApiKeyService.create_key(user)

        second_key, _ = ApiKeyService.create_key(user)
        first_revoke_time = ApiKey.objects.get(pk=first_key.pk).revoke_time

        ApiKeyService.create_key(user)

        first_key.refresh_from_db()
        second_key.refresh_from_db()
        assert first_key.revoke_time == first_revoke_time
        assert second_key.revoke_time == approx_now()
        assert user.api_keys.filter(revoke_time__isnull=True).count() == 1
        assert user.api_keys.count() == 3


@pytest.mark.django_db
class TestGetCurrentKey:
    def test_returns_active_key(self, user: User) -> None:
        ApiKeyService.create_key(user)

        result = ApiKeyService.get_current_key(user)
        assert result is not None
        assert result.revoke_time is None

    def test_returns_none_when_no_key(self, user: User) -> None:
        assert ApiKeyService.get_current_key(user) is None

    def test_returns_none_when_only_revoked(self, user: User) -> None:
        ApiKeyService.create_key(user)
        ApiKeyService.revoke_key(user)

        assert ApiKeyService.get_current_key(user) is None


@pytest.mark.django_db
class TestRevokeKey:
    def test_returns_revoked_key(self, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        assert ApiKeyService.revoke_key(user) == api_key

        api_key.refresh_from_db()
        assert api_key.revoke_time == approx_now()

    def test_returns_none_when_no_active_key(self, user: User) -> None:
        assert ApiKeyService.revoke_key(user) is None

    def test_preserves_revoked_key_rows(self, user: User) -> None:
        ApiKeyService.create_key(user)
        ApiKeyService.revoke_key(user)

        assert user.api_keys.count() == 1
        assert user.api_keys.filter(revoke_time__isnull=False).count() == 1


@pytest.mark.django_db
class TestAuthenticateKey:
    def test_valid_key(self, user: User) -> None:
        _, plaintext = ApiKeyService.create_key(user)

        result = ApiKeyService.authenticate_key(plaintext)

        assert result is not None
        assert result.user_id == user.pk

    def test_invalid_key(self) -> None:
        assert ApiKeyService.authenticate_key("cfk_nonexistent") is None

    def test_revoked_key(self, user: User) -> None:
        _, plaintext = ApiKeyService.create_key(user)
        ApiKeyService.revoke_key(user)

        assert ApiKeyService.authenticate_key(plaintext) is None

    def test_inactive_user(self, user: User) -> None:
        _, plaintext = ApiKeyService.create_key(user)

        update_object(user, is_active=False)

        assert ApiKeyService.authenticate_key(plaintext) is None

    def test_valid_after_user_reactivation(self, user: User) -> None:
        _, plaintext = ApiKeyService.create_key(user)

        update_object(user, is_active=False)
        assert ApiKeyService.authenticate_key(plaintext) is None

        update_object(user, is_active=True)
        result = ApiKeyService.authenticate_key(plaintext)
        assert result is not None
        assert result.user_id == user.pk

    def test_auto_revokes_on_auth_hash_mismatch(self, user: User) -> None:
        api_key, plaintext = ApiKeyService.create_key(user)

        user.set_password("new-password")
        user.save(update_fields=["password"])

        result = ApiKeyService.authenticate_key(plaintext)

        assert result is None
        api_key.refresh_from_db()
        assert api_key.revoke_time is not None


@pytest.mark.django_db
class TestTouchLastUse:
    def test_updates_when_none(self, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)
        assert api_key.last_use_time is None

        ApiKeyService.touch_last_use(api_key)

        api_key.refresh_from_db()
        assert api_key.last_use_time == approx_now()

    def test_updates_when_stale(self, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)
        stale = (
            timezone.now()
            - ApiKeyService.last_use_update_interval
            - timedelta(seconds=1)
        )
        update_object(api_key, last_use_time=stale)

        ApiKeyService.touch_last_use(api_key)

        api_key.refresh_from_db()
        assert api_key.last_use_time == approx_now()

    def test_skips_when_recent(self, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)
        recent = (
            timezone.now()
            - ApiKeyService.last_use_update_interval
            + timedelta(seconds=1)
        )
        update_object(api_key, last_use_time=recent)

        ApiKeyService.touch_last_use(api_key)

        api_key.refresh_from_db()
        assert api_key.last_use_time == recent

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.http import HttpRequest
from django.test import RequestFactory
from pytest_mock import MockerFixture

from app.core.models import ApiKey, ApiKeySession, User
from app.core.services import ApiKeyService
from tests.helpers import approx_now, update_object


def make_request_with_session(rf: RequestFactory) -> HttpRequest:
    request = rf.post("/")
    session = SessionStore()
    session.create()
    request.session = session
    return request


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

    def test_rotation_deletes_linked_sessions(
        self,
        rf: RequestFactory,
        user: User,
    ) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)

        session_key = request.session.session_key
        assert Session.objects.filter(pk=session_key).exists()

        ApiKeyService.create_key(user)

        assert not Session.objects.filter(pk=session_key).exists()


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

    def test_deletes_linked_sessions(
        self,
        rf: RequestFactory,
        user: User,
    ) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)
        session_key = request.session.session_key

        ApiKeyService.revoke_key(user)

        assert not Session.objects.filter(pk=session_key).exists()
        assert not ApiKeySession.objects.filter(api_key=api_key).exists()

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

    def test_auto_revoke_deletes_linked_sessions(
        self,
        rf: RequestFactory,
        user: User,
    ) -> None:
        api_key, plaintext = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)
        session_key = request.session.session_key

        user.set_password("new_pw")
        user.save(update_fields=["password"])

        ApiKeyService.authenticate_key(plaintext)

        assert not Session.objects.filter(pk=session_key).exists()


@pytest.mark.django_db
class TestApiKeyLogin:
    def test_creates_session(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)

        assert get_user(request) == user

    def test_creates_linking_row(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)

        link = ApiKeySession.objects.get(api_key=api_key)
        assert link.session_id == request.session.session_key

    def test_sets_short_expiry(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)

        expected = settings.API_KEY_SESSION_EXPIRY.total_seconds()
        assert request.session.get_expiry_age() == pytest.approx(expected, abs=2)

    def test_updates_last_use_time(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)
        assert api_key.last_use_time is None

        request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request, api_key)

        api_key.refresh_from_db()
        assert api_key.last_use_time == approx_now()

    def test_replaces_existing_session(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        first_request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request=first_request, api_key=api_key)
        first_session_key = first_request.session.session_key

        second_request = make_request_with_session(rf)
        ApiKeyService.api_key_login(request=second_request, api_key=api_key)
        second_session_key = second_request.session.session_key

        assert first_session_key != second_session_key
        assert not Session.objects.filter(pk=first_session_key).exists()
        assert Session.objects.filter(pk=second_session_key).exists()
        assert ApiKeySession.objects.filter(api_key=api_key).count() == 1

    def test_rejects_revoked_key(self, rf: RequestFactory, user: User) -> None:
        api_key, _ = ApiKeyService.create_key(user)
        ApiKeyService.revoke_key(user)

        request = make_request_with_session(rf)
        with pytest.raises(ValueError, match="revoked"):
            ApiKeyService.api_key_login(request, api_key)

    @pytest.mark.django_db(transaction=True)
    def test_transaction_rollback_on_failure(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        user: User,
    ) -> None:
        api_key, _ = ApiKeyService.create_key(user)

        # Make the linking row creation fail after login() has already created a
        # session. The transaction should roll back the session too.
        mocker.patch.object(
            ApiKeySession.objects,
            "create",
            side_effect=RuntimeError("Simulated failure"),
        )

        request = make_request_with_session(rf)
        sessions_before = Session.objects.count()

        with pytest.raises(RuntimeError, match="Simulated failure"):
            ApiKeyService.api_key_login(request, api_key)

        assert not ApiKeySession.objects.filter(api_key=api_key).exists()
        assert Session.objects.count() == sessions_before
        api_key.refresh_from_db()
        assert api_key.last_use_time is None

import secrets
from datetime import timedelta
from hashlib import sha256

from django.utils import timezone

from app.core.models import ApiKey, User
from app.infra.models import Mutex

# TODO: Add a periodic job to auto-revoke API keys unused for 30 days (based on
#  last_use_time, or create_time if never used). This catches forgotten keys, keys from
#  departed users, and keys compromised but not yet exploited.


class ApiKeyService:
    key_length = 32
    last_use_update_interval = timedelta(hours=1)

    @classmethod
    def create_key(cls, user: User) -> tuple[ApiKey, str]:
        """Create a new API key for the user, revoking any existing active key.

        The caller is responsible for verifying the user's password before calling this
        method. Returns the created model instance and the plaintext key (shown once,
        never stored).
        """
        with Mutex.lock_in_transaction(str(user.pk), namespace="api_key"):
            cls._revoke_active_key(user)

            plaintext = cls._generate_key()
            api_key = ApiKey.objects.create(
                user=user,
                hashed_key=cls._hash_key(plaintext),
                auth_hash=user.get_session_auth_hash(),
            )
            return api_key, plaintext

    @classmethod
    def get_current_key(cls, user: User) -> ApiKey | None:
        """Return the active (non-revoked) API key for the user, or None."""
        return user.api_keys.filter(revoke_time__isnull=True).first()

    @classmethod
    def revoke_key(cls, user: User) -> ApiKey | None:
        """Revoke the active API key for the user.

        Returns the revoked key, or ``None`` if no active key existed.
        """
        with Mutex.lock_in_transaction(str(user.pk), namespace="api_key"):
            return cls._revoke_active_key(user)

    @classmethod
    def authenticate_key(cls, raw_key: str) -> ApiKey | None:
        """Authenticate a raw API key and return the ApiKey with its user.

        Returns ``None`` if the key is invalid, revoked, belongs to an inactive user, or
        has a stale auth hash (password changed since key creation). A stale auth hash
        triggers auto-revocation of the key.
        """
        hashed = cls._hash_key(raw_key)
        api_key = (
            ApiKey.objects.select_related("user")
            .filter(hashed_key=hashed, revoke_time__isnull=True)
            .first()
        )
        if api_key is None:
            return None

        user = api_key.user
        if not user.is_active:
            # Deliberately not revoking: the key should survive temporary deactivation
            # and remain valid if the user is reactivated with the same password.
            return None

        if api_key.auth_hash != user.get_session_auth_hash():
            # Auth hash check runs outside the lock as an optimization for the common
            # case (matching hash). The lock, refresh, and re-check below prevent
            # double-revocation when concurrent requests both detect the mismatch.
            with Mutex.lock_in_transaction(str(user.pk), namespace="api_key"):
                api_key.refresh_from_db()
                if api_key.revoke_time is None:  # pragma: no branch
                    cls._revoke(api_key)
            return None

        return api_key

    @classmethod
    def touch_last_use(cls, api_key: ApiKey) -> None:
        """Update ``last_use_time`` if it is stale beyond the update interval.

        Avoids a write on every request; hourly granularity is sufficient for the
        auto-revocation policy.
        """
        now = timezone.now()
        if (
            api_key.last_use_time is not None
            and now - api_key.last_use_time < cls.last_use_update_interval
        ):
            return
        api_key.last_use_time = now
        api_key.save(update_fields=["last_use_time"])

    @classmethod
    def _revoke_active_key(cls, user: User) -> ApiKey | None:
        api_key = cls.get_current_key(user)
        if api_key is not None:
            cls._revoke(api_key)
        return api_key

    @classmethod
    def _revoke(cls, api_key: ApiKey) -> None:
        api_key.revoke_time = timezone.now()
        api_key.save(update_fields=["revoke_time"])

    @classmethod
    def _generate_key(cls) -> str:
        return f"{ApiKey.KEY_PREFIX}{secrets.token_urlsafe(cls.key_length)}"

    @classmethod
    def _hash_key(cls, key: str) -> str:
        # Unsalted SHA-256 is sufficient because the input is a 256-bit random key, not
        # a human-chosen password. Do not reuse for low-entropy secrets.
        return sha256(key.encode()).hexdigest()

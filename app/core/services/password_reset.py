import secrets
from functools import partial
from hashlib import sha256

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models.functions import Now
from django.template.loader import render_to_string
from loguru import logger

from app.core.models import PasswordResetToken, User
from app.core.types import Password
from app.infra.models import Mutex
from app.utils.sanitization import sanitize_email_subject

normalize_email = User.objects.normalize_email


class PasswordResetService:
    token_length = 32

    password_reset_email_subject = "core/password-reset-email-subject.html"  # noqa: S105
    password_reset_email_body = "core/password-reset-email-body.html"  # noqa: S105

    @classmethod
    def create_token(
        cls,
        user: User,
        *,
        password_reset_page_uri: str,
    ) -> PasswordResetToken | None:
        """Create a password reset token for a given user.

        If there is already a token created recently, return ``None``.
        """
        # Lock by normalized email to serialize operations per email address. The
        # transaction alone doesn't provide row-level locking, and there's no guarantee
        # a row exists to lock. Mutex ensures concurrent requests for the same email
        # are serialized, preventing race conditions in rate limiting and token
        # creation.
        with Mutex.lock_in_transaction(
            normalize_email(user.email),
            namespace=cls.__name__,
        ):
            if PasswordResetToken.objects.filter(
                user=user,
                create_time__gte=Now() - settings.PASSWORD_RESET_TOKEN_INTERVAL,
            ).exists():
                return None

            token = cls.generate_token()
            token_hash = cls.hash_token(token)
            password_reset_token = PasswordResetToken.objects.create(
                user=user,
                token_hash=token_hash,
                expire_time=Now() + settings.PASSWORD_RESET_TOKEN_EXPIRY,
            )
            # Refresh to load database-generated fields (create_time, expire_time with
            # database functions) before passing to the on_commit callback.
            password_reset_token.refresh_from_db()
            logger.info("Password reset token created.", user_uid=user.uid)
            # Defer email sending until after transaction commits. If the transaction
            # rolls back, we don't want to send emails for data that was never
            # persisted.
            transaction.on_commit(
                partial(
                    cls.send_password_reset_email,
                    user,
                    token,
                    password_reset_page_uri=password_reset_page_uri,
                )
            )
            return password_reset_token

    @classmethod
    def consume_token(cls, user: User, token: str, new_password: Password) -> bool:
        """Consume a password reset token and set new password for the given user.

        Returns:
            Whether the password reset token was successfully consumed.
        """
        active_tokens = PasswordResetToken.objects.filter(
            user=user,
            expire_time__gte=Now(),
            consume_time__isnull=True,
        )
        # Lock by normalized email to serialize operations per email address. The
        # transaction alone doesn't provide row-level locking, and there's no guarantee
        # a row exists to lock. Mutex ensures concurrent token consumption attempts for
        # the same user are serialized, preventing race conditions.
        with Mutex.lock_in_transaction(
            normalize_email(user.email),
            namespace=cls.__name__,
        ):
            updated = active_tokens.filter(token_hash=cls.hash_token(token)).update(
                consume_time=Now()
            )
            if not updated:
                return False

            # Invalidate other tokens.
            active_tokens.update(expire_time=Now())

            user.set_password(new_password.get_secret_value())
            user.save(update_fields=["password"])
            logger.info("Password reset token consumed.", user_uid=user.uid)
            return True

    @classmethod
    def generate_token(cls) -> str:
        return secrets.token_urlsafe(cls.token_length)

    @classmethod
    def hash_token(cls, token: str) -> str:
        return sha256(token.encode()).hexdigest()

    @classmethod
    def send_password_reset_email(
        cls,
        user: User,
        token: str,
        *,
        password_reset_page_uri: str,
    ) -> None:
        fragment = f"{user.uid}:{token}"
        context = {
            "site_name": settings.SITE_NAME,
            "reset_link": f"{password_reset_page_uri}#{fragment}",
            "reset_link_expiry_minutes": int(
                settings.PASSWORD_RESET_TOKEN_EXPIRY.total_seconds() // 60
            ),
            "user": user,
        }
        render = partial(render_to_string, context=context)

        subject: str = render(cls.password_reset_email_subject)
        subject = sanitize_email_subject(subject)

        body = render(cls.password_reset_email_body)

        logger.info(
            "Sending password reset email.",
            user_uid=user.uid,
            email=user.email,
        )
        mail = EmailMessage(subject, body, to=[user.email])
        mail.send()

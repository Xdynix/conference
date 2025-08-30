__all__ = (
    "PasswordResetService",
    "PermissionService",
)

import secrets
from collections.abc import Container
from functools import partial
from hashlib import sha256

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models.functions import Now
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from loguru import logger

from app.core.models import PasswordResetToken, Permission, User
from app.core.types import Password
from app.infra.models import Mutex

normalize_email = User.objects.normalize_email


class PermissionService:
    @classmethod
    async def get_permissions(cls, user: User | AnonymousUser) -> Container[str]:
        """Return the globally granted permission keys for a given user."""
        if not user.is_active or user.is_anonymous:
            return set()

        if user.is_superuser:
            permissions = Permission.objects.all()
        else:
            permissions = Permission.objects.filter(role__assignment__user=user)

        return await Permission.to_keys(permissions)


class PasswordResetService:
    token_length = 32

    password_reset_email_subject = "core/password-reset-email-subject.html"  # noqa: S105
    password_reset_email_body = "core/password-reset-email-body.html"  # noqa: S105

    @classmethod
    @sync_to_async
    @logger.catch(reraise=True)
    def create_token(
        cls,
        user: User,
        request: HttpRequest,
    ) -> PasswordResetToken | None:
        """Create a password reset token for a given user.

        If there is already a token created recently, return ``None``.
        """
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
            password_reset_token.refresh_from_db()
            logger.info("Password reset token created.", user=user)
            transaction.on_commit(
                partial(cls.send_password_reset_email, user, token, request)
            )
            return password_reset_token

    @classmethod
    @sync_to_async
    @logger.catch(reraise=True)
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
            logger.info("Password reset token consumed.", user=user)
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
        request: HttpRequest,
    ) -> None:
        password_reset_page_uri = (
            settings.PASSWORD_RESET_PAGE_URI
            # Fallback to minimum password reset page.
            or request.build_absolute_uri(reverse("core:password-reset"))
        )
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

        # Prevent header injection by removing newlines.
        subject: str = render(cls.password_reset_email_subject)
        subject = "".join(subject.splitlines())

        body = render(cls.password_reset_email_body)

        logger.info("Sending password reset email.", email=user.email)
        mail = EmailMessage(subject, body, to=[user.email])
        mail.send()

import os
import secrets
import string
from functools import partial
from hashlib import sha256
from typing import cast

import jwt
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.functions import Now
from django.template.loader import render_to_string
from django.utils import timezone
from loguru import logger

from app.infra.models import Mutex
from app.verikit.models import EmailVerification


class EmailVerificationService:
    """Service for handling email verifications."""

    code_length = 6
    code_chars = string.digits
    code_salt_size = 16
    jwt_algorithm = "HS256"
    jwt_iss = "verikit.email"

    verification_email_subject = "verikit/verification-email-subject.html"
    verification_email_body = "verikit/verification-email-body.html"

    @classmethod
    @sync_to_async
    @logger.catch(reraise=True)
    def issue_code(cls, email: str) -> EmailVerification | None:
        """Issues a new verification code for the given email address.

        If there is already a verification code created recently, returns ``None``.

        Args:
            email: The email address to verify.

        Returns:
            The ``EmailVerification`` object if a code was issued, otherwise ``None``.
        """
        with Mutex.lock_in_transaction(email.lower(), namespace=cls.__name__):
            if (
                cls.active_verifications(email)
                .filter(create_time__gte=Now() - settings.VERIKIT_EMAIL_CODE_INTERVAL)
                .exists()
            ):
                return None

            code = cls.generate_code()
            code_salt, code_hash = cls.hash_code(code)
            email_verification = EmailVerification.objects.create(
                email=email,
                code_salt=code_salt,
                code_hash=code_hash,
                expire_time=Now() + settings.VERIKIT_EMAIL_CODE_EXPIRY,
            )
            email_verification.refresh_from_db()
            logger.info("Verification code issued.", email=email)
            transaction.on_commit(partial(cls.send_verification_email, email, code))
            return email_verification

    @classmethod
    @sync_to_async
    @logger.catch(reraise=True)
    def verify_code(cls, email: str, code: str) -> str | None:
        """Verifies the given code for the given email address.

        Upon successful verification, all other active codes for the same email address
        will be invalidated and a JWT token is returned.

        Args:
            email: The email address to verify.
            code: The verification code.

        Returns:
            A JWT token if the code is valid, otherwise `None`.
        """
        with Mutex.lock_in_transaction(email.lower(), namespace=cls.__name__):
            active_verifications = cls.active_verifications(email)
            if not any(
                cls.check_code(email_verification, code)
                for email_verification in active_verifications
            ):
                return None

            # Invalidate other verifications.
            cls.active_verifications(email).update(verify_time=Now())

            logger.info("Verification code verified.", email=email)
            return cls.sign_jwt(email)

    @classmethod
    def verify_token(cls, token: str) -> str | None:
        """Verifies a JWT email verification token and extracts the email address.

        Args:
            token: The JWT token to verify.

        Returns:
            The normalized email address from the token if valid, otherwise ``None``.
            Returns ``None`` for expired, malformed, or tokens with invalid issuer.
        """

        try:
            payload = jwt.decode(
                token,
                settings.VERIKIT_EMAIL_TOKEN_SECRET,
                algorithms=["HS256"],
                issuer=cls.jwt_iss,
            )
            return cast(str, payload["sub"].lower())
        except (jwt.InvalidTokenError, KeyError):
            return None

    @classmethod
    def active_verifications(cls, email: str) -> QuerySet[EmailVerification]:
        """Return a queryset of active verifications for the given email address.

        Args:
            email: The email address to check.

        Returns:
            A queryset of active ``EmailVerification`` objects.
        """
        return EmailVerification.objects.filter(
            email__iexact=email,
            expire_time__gte=Now(),
            verify_time__isnull=True,
        )

    @classmethod
    def generate_code(cls) -> str:
        """Generates a random verification code.

        Returns:
            A random verification code.
        """
        return "".join(secrets.choice(cls.code_chars) for _ in range(cls.code_length))

    @classmethod
    def hash_code(cls, code: str) -> tuple[bytes, bytes]:
        """Hashes the given code with a random salt.

        Args:
            code: The code to hash.

        Returns:
            A tuple containing the salt and the hash.
        """
        code_salt = os.urandom(cls.code_salt_size)
        code_hash = sha256(code_salt + code.encode())
        return code_salt, code_hash.digest()

    @classmethod
    def check_code(cls, email_verification: EmailVerification, code: str) -> bool:
        """Checks the given code against the given email verification object.

        Args:
            email_verification: The ``EmailVerification`` object to check against.
            code: The code to check.

        Returns:
            ``True`` if the code is valid, otherwise ``False``.
        """
        code_hash = sha256(bytes(email_verification.code_salt) + code.encode())
        return secrets.compare_digest(
            code_hash.digest(),
            email_verification.code_hash,
        )

    @classmethod
    def send_verification_email(cls, email: str, code: str) -> None:
        """Sends a verification email to the given email address.

        Args:
            email: The email address to send the verification code to.
            code: The verification code.
        """
        context = {
            "site_name": settings.SITE_NAME,
            "code": code,
        }
        render = partial(render_to_string, context=context)

        # Prevent header injection by removing newlines.
        subject: str = render(cls.verification_email_subject)
        subject = "".join(subject.splitlines())

        body = render(cls.verification_email_body)

        logger.info("Sending verification email.", email=email)
        mail = EmailMessage(subject, body, to=[email])
        mail.send()

    @classmethod
    def sign_jwt(cls, email: str) -> str:
        """Signs a JWT token for the given email address.

        Args:
            email: The email address to include in the token.

        Returns:
            A JWT token string.
        """
        now = timezone.now()
        payload = {
            "sub": email,
            "exp": now + settings.VERIKIT_EMAIL_TOKEN_EXPIRY,
            "iat": now,
            "iss": cls.jwt_iss,
        }
        return jwt.encode(
            payload,
            settings.VERIKIT_EMAIL_TOKEN_SECRET,
            algorithm=cls.jwt_algorithm,
        )

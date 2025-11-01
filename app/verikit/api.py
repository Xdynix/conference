from http import HTTPStatus
from typing import Annotated, Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from pydantic import AwareDatetime, StringConstraints

from app.ninja.errors import ErrorResponse
from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.throttling import AnonThrottle, SimpleThrottle, throttling
from app.verikit.models import EmailVerification
from app.verikit.services import EmailVerificationService
from app.verikit.types import EmailStr

router = Router(tags=["Verikit"])


class CreateEmailVerificationRequest(Schema):
    email: EmailStr


class CreateEmailVerificationResponse(Schema):
    email: EmailStr
    create_time: AwareDatetime
    expire_time: AwareDatetime


@router.post(
    "/email-verifications",
    response={
        HTTPStatus.CREATED: CreateEmailVerificationResponse,
        HTTPStatus.TOO_MANY_REQUESTS: ErrorResponse,
    },
    summary="Issue Code",
)
@decorate_view(throttling(AnonThrottle("100/min")))
@decorate_view(cf_turnstile_required)
async def create_email_verification(
    request: HttpRequest,  # noqa: ARG001
    payload: CreateEmailVerificationRequest,
) -> tuple[int, EmailVerification] | JsonResponse:
    """Issue a verification code for the given email address.

    Returns the verification details if successful. Returns 429 if a verification code
    was recently issued for this email.
    """
    email_verification = await EmailVerificationService.issue_code(payload.email)
    if email_verification is None:
        message = _("A verification code was recently issued for this email address.")
        interval_seconds = int(settings.VERIKIT_EMAIL_CODE_INTERVAL.total_seconds())
        return JsonResponse(
            ErrorResponse(message=message).model_dump(),
            status=HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(interval_seconds)},
        )
    return HTTPStatus.CREATED, email_verification


class VerifyEmailVerificationRequest(Schema):
    email: EmailStr
    code: Annotated[
        str,
        StringConstraints(min_length=1, max_length=32),
    ]


class VerifyEmailVerificationResponse(Schema):
    email: EmailStr
    token: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]


class PayloadEmailThrottle(SimpleThrottle):
    """Throttle by email from the already-parsed Ninja payload.

    Reads the ``email`` field from the parsed ``payload`` argument and uses it as the
    cache key. Do not wrap this with ``decorate_view`` so it runs after Ninja has parsed
    the request body.
    """

    async def get_cache_key(
        self,
        *_: Any,
        payload: VerifyEmailVerificationRequest,
        **__: Any,
    ) -> str | None:
        return payload.email


@router.post(
    "/email-verifications:verify",
    response={
        HTTPStatus.OK: VerifyEmailVerificationResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Verify Code",
)
@decorate_view(throttling(AnonThrottle("100/min")))
@decorate_view(cf_turnstile_required)
@throttling(PayloadEmailThrottle("20/min"))
async def verify_email_verification(
    request: HttpRequest,  # noqa: ARG001
    payload: VerifyEmailVerificationRequest,
) -> VerifyEmailVerificationResponse:
    """Verify a verification code and return a signed verification token.

    Returns 422 if the code is invalid or expired.
    """
    token = await EmailVerificationService.verify_code(payload.email, payload.code)
    if token is None:
        raise HttpError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            _("Invalid or expired verification code."),
        )

    return VerifyEmailVerificationResponse(
        email=payload.email,
        token=token,
    )

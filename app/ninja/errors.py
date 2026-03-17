__all__ = (
    "ErrorResponse",
    "make_validation_error",
    "set_exception_handlers",
)

from collections.abc import Callable, Sequence
from http import HTTPStatus
from typing import Any, cast

from django.http import Http404, HttpResponse
from django.http import HttpRequest as DjangoHttpRequest
from django.utils.translation import gettext as _
from loguru import logger
from ninja import NinjaAPI, Schema
from ninja.errors import (
    AuthenticationError,
    AuthorizationError,
    HttpError,
    ValidationError,
)
from ninja.types import DictStrAny


class ErrorResponse(Schema):
    message: str
    details: list[DictStrAny] | None = None


ExcHandlerReturn = tuple[int, ErrorResponse]
type ExcHandler[Exc: Exception] = Callable[[Exc | type[Exc]], ExcHandlerReturn]


def make_validation_error(
    *,
    path: str | Sequence[str | int],
    message: str | Sequence[str],
    type_: str = "value_error",
) -> ValidationError:
    """Create a validation error with Django Ninja's standard error structure.

    Returns:
        A validation error formatted for consistent API error responses.
    """
    if isinstance(path, str):  # pragma: no branch
        path = [path]
    if isinstance(message, str):
        message = [message]
    return ValidationError(
        errors=[
            {
                "type": type_,
                "loc": ["body", "payload", *path],
                "msg": msg,
            }
            for msg in message
        ]
    )


def set_exception_handlers(api: NinjaAPI) -> None:
    """Set custom exception handlers."""

    def exception_handler[Exc: Exception](
        exc_type: type[Exc],
    ) -> Callable[[ExcHandler[Exc]], None]:
        """Register custom exception handler."""

        def decorator(handle: ExcHandler[Exc]) -> None:
            def wrapped(
                request: DjangoHttpRequest,
                exc: Exc | type[Exc],
            ) -> HttpResponse:
                status, response = handle(exc)
                return api.create_response(
                    request,
                    response.model_dump(exclude_none=True),
                    status=status,
                )

            api.add_exception_handler(exc_type, wrapped)

        return decorator

    @exception_handler(Exception)
    def handle_exception(__: Any) -> ExcHandlerReturn:
        logger.exception("Unexpected exception during request handling.")
        message = _("An unexpected error has occurred.")
        return HTTPStatus.INTERNAL_SERVER_ERROR, ErrorResponse(message=message)

    @exception_handler(Http404)
    def handle_404(__: Any) -> ExcHandlerReturn:
        message = _("The requested resource could not be found.")
        return HTTPStatus.NOT_FOUND, ErrorResponse(message=message)

    @exception_handler(HttpError)
    def handle_http_error(exc: HttpError | type[HttpError]) -> ExcHandlerReturn:
        exc = cast(HttpError, exc)
        return exc.status_code, ErrorResponse(message=exc.message)

    @exception_handler(ValidationError)
    def handle_validation_error(
        exc: ValidationError | type[ValidationError],
    ) -> ExcHandlerReturn:
        # TODO: Clean up Pydantic error details before returning to clients.
        #
        # Current issues with exc.errors:
        #
        # 1. Union types add internal type names to `loc`:
        #    Schema: `email: EmailStr | Literal[""]`
        #    Loc: ["body", "payload", "email", "function-after[normalize_email(), ...]"]
        #    Loc: ["body", "payload", "email", "literal['']"]
        #
        # 2. Union alternatives produce multiple errors for one field:
        #    Msgs: "value is not a valid email address: ..."
        #          "Input should be ''"
        #
        # 3. Verbose prefixes in messages:
        #    Msg: "value is not a valid email address: The part after the @-sign..."
        #
        # Suggested fix: Transform exc.errors to:
        # - Filter loc parts containing "[" or "|" (internal type descriptors)
        # - Skip unhelpful messages like "Input should be '...'"
        # - Strip verbose prefixes from email validation messages
        # - Deduplicate errors for the same field path
        exc = cast(ValidationError, exc)
        message = _("Invalid payload.")
        return HTTPStatus.UNPROCESSABLE_ENTITY, ErrorResponse(
            message=message,
            details=exc.errors,
        )

    @exception_handler(AuthorizationError)
    def handle_authorization_error(__: Any) -> ExcHandlerReturn:
        message = _("You are not allowed to perform this action.")
        return HTTPStatus.FORBIDDEN, ErrorResponse(message=message)

    @exception_handler(AuthenticationError)
    def handle_authentication_error(__: Any) -> ExcHandlerReturn:
        message = _("Authentication failed or missing.")
        return HTTPStatus.UNAUTHORIZED, ErrorResponse(message=message)

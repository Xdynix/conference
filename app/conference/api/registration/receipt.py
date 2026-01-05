from http import HTTPStatus

from django.http import HttpRequest, HttpResponse
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from loguru import logger
from ninja import Field, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Receipt,
    Registration,
    RegistrationState,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import RegistrationResponse, prefetch_registration, router

# TODO: Add PDF generation for receipts. Current gap: HTML to PDF conversion requires
#  either OS-level libraries (xhtml2pdf, WeasyPrint with system deps) or a headless
#  browser (Playwright, Puppeteer), with no elegant pure Python solution.
#
# TODO: Add receipt email sending endpoint.
#
# TODO: Add endpoint to upload externally generated PDF to be sent with the email, as a
#  workaround until PDF generation is implemented.

jinja_env = SandboxedEnvironment(
    autoescape=True,
    undefined=StrictUndefined,
)


class GenerateReceiptRequest(Schema):
    template: str = Field(min_length=1, max_length=500_000)


@router.post(
    (
        "/conferences/{slug:conference_name}/registrations/{ulid:registration_uid}"
        "/receipt:generate"
    ),
    response={
        HTTPStatus.OK: RegistrationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Generate Receipt",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def generate_receipt(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
    payload: GenerateReceiptRequest,
) -> Registration:
    """Generate a receipt for a registration.

    Renders the provided Jinja2 template with registration context and stores the
    result. Regenerating replaces any existing receipt.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    registration = await aget_object_or_404(
        conference.registrations.select_related(
            "conference",
            "user__profile",
            "paper__track__conference",
            "attendance_type",
        ).prefetch_related(
            "payment_items__payment",
            "paper__authors",
        ),
        uid=registration_uid,
    )

    if registration.state == RegistrationState.CANCELLED:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Cannot generate receipt for cancelled registration."),
        )

    try:
        jinja_env.parse(payload.template)
    except TemplateSyntaxError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    try:
        rendered_html = jinja_env.from_string(payload.template).render(
            registration=registration,
        )
    except UndefinedError as exc:
        raise make_validation_error(path="template", message=str(exc)) from exc

    await Receipt.objects.aupdate_or_create(
        registration=registration,
        defaults={"rendered_html": rendered_html},
    )

    logger.info(
        "Receipt generated.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_registration(registration)


GET_RECEIPT_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {"text/html": {"schema": {"type": "string"}}},
        }
    }
}


@router.get(
    "/conferences/-/registrations/{ulid:uid}/receipt",
    openapi_extra=GET_RECEIPT_OPENAPI_EXTRA,
    summary="Get Receipt",
    auth=None,
)
async def get_receipt(
    request: HttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse:
    """Retrieve the rendered receipt for a registration."""
    receipt = await aget_object_or_404(Receipt, registration__uid=uid)
    return HttpResponse(receipt.rendered_html, content_type="text/html")

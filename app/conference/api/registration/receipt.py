import asyncio
import json
from functools import partial
from http import HTTPStatus
from typing import Any, cast

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Schema
from ninja.errors import HttpError
from pydantic import AwareDatetime
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    PaymentItem,
    Receipt,
    Registration,
    RegistrationState,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error
from app.utils.enums import Region
from app.utils.files import build_file_download_response
from app.utils.typst import (
    CompilationError,
    compile_template,
    load_assets,
    typst_json_default,
)

from .core import RegistrationResponse, prefetch_registration, router

COMPILE_TIMEOUT = 5.0

PREVIEW_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    }
}


class GenerateReceiptRequest(Schema):
    template: str = Field(min_length=1, max_length=500_000)
    extra_context: dict[str, Any] = Field(default_factory=dict)


async def _resolve_and_compile_receipt(
    conference_name: str,
    registration_uid: ULID,
    template: str,
    extra_context: dict[str, Any],
) -> tuple[Conference, Registration, bytes, dict[str, Any]]:
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    registration = await aget_object_or_404(
        conference.registrations.select_related(
            "conference",
            "user__profile",
            "paper__track",
            "attendance_type",
        ).prefetch_related(
            Prefetch(
                "payment_items",
                queryset=PaymentItem.objects.select_related("payment").order_by("id"),
            ),
            "paper__authors",
        ),
        uid=registration_uid,
    )

    if registration.state == RegistrationState.CANCELLED:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Cannot generate receipt for cancelled registration."),
        )

    paper_data = None
    if registration.paper is not None:
        paper = registration.paper
        paper_data = {
            "code": paper.code,
            "title": paper.title,
            "track": {"display_name": paper.track.display_name},
            "authors": [
                {
                    "given_name": a.given_name,
                    "family_name": a.family_name,
                    "affiliation": a.affiliation,
                    "region_code": a.region_code,
                    "region_name": Region.get_label(a.region_code),
                    "email": a.email,
                    "phone": a.phone,
                    "corresponding": a.corresponding,
                }
                for a in paper.authors.all()
            ],
        }
    profile = getattr(registration.user, "profile", None)
    context: dict[str, Any] = {
        "conference": {
            "name": registration.conference.name,
            "display_name": registration.conference.display_name,
            "start_date": registration.conference.start_date,
            "end_date": registration.conference.end_date,
            "location": registration.conference.location,
        },
        "registration": {
            "uid": registration.uid,
            "create_date": registration.create_time.date(),
            "reference_code": registration.reference_code,
            "title": registration.get_title_display(),
            "given_name": registration.given_name,
            "family_name": registration.family_name,
            "affiliation": registration.affiliation,
            "region_code": registration.region_code,
            "region_name": Region.get_label(registration.region_code),
            "email": registration.email,
            "phone": registration.phone,
            "receipt_title": registration.receipt_title,
            "attendance_type": {
                "display_name": registration.attendance_type.display_name,
            },
            "user": {
                "given_name": getattr(profile, "given_name", ""),
                "family_name": getattr(profile, "family_name", ""),
                "affiliation": getattr(profile, "affiliation", ""),
                "region_code": getattr(profile, "region_code", ""),
                "region_name": Region.get_label(getattr(profile, "region_code", "")),
                "email": registration.user.email,
            },
            "paper": paper_data,
            "payment_items": [
                {
                    "description": item.description,
                    "amount": item.amount,
                    "formatted_amount": item.formatted_amount,
                }
                for item in registration.payment_items.all()
            ],
        },
        "extra": extra_context,
    }
    context = json.loads(json.dumps(context, default=typst_json_default))

    def compile_pdf() -> bytes:
        return compile_template(
            template,
            context,
            files=load_assets(settings.TYPST_ASSET_DIR),
            font_paths=[settings.TYPST_FONT_DIR],
        )

    try:
        pdf_bytes = await asyncio.wait_for(
            sync_to_async(compile_pdf)(),
            timeout=COMPILE_TIMEOUT,
        )
    except CompilationError as exc:
        raise make_validation_error(path="template", message=str(exc)) from exc
    except TimeoutError as exc:
        raise make_validation_error(
            path="template",
            message=_("Template compilation timed out."),
        ) from exc

    return conference, registration, pdf_bytes, context


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

    Compiles the provided typst template with registration context and stores the
    resulting PDF. Regenerating replaces any existing receipt.
    """
    conference, registration, pdf_bytes, context = await _resolve_and_compile_receipt(
        conference_name,
        registration_uid,
        payload.template,
        payload.extra_context,
    )

    @sync_to_async
    def save_receipt() -> None:
        with transaction.atomic():
            old_pdf_name = (
                Receipt.objects.filter(registration=registration)
                .values_list("rendered_pdf", flat=True)
                .first()
            )

            receipt, __ = Receipt.objects.update_or_create(
                registration=registration,
                defaults={"template": payload.template, "context": context},
            )
            receipt.rendered_pdf.save("receipt.pdf", ContentFile(pdf_bytes), save=False)
            receipt.save(update_fields=["rendered_pdf"])

            if old_pdf_name and old_pdf_name != receipt.rendered_pdf.name:
                storage = receipt.rendered_pdf.storage
                transaction.on_commit(partial(storage.delete, old_pdf_name))

    await save_receipt()

    await audit(
        request=request,
        action=AuditAction.REGISTRATION_GENERATE_RECEIPT,
        resource=registration,
        scope=conference.name,
        payload=payload,
        detail={"context": context},
    )

    return await prefetch_registration(registration, request)


@router.post(
    (
        "/conferences/{slug:conference_name}/registrations/{ulid:registration_uid}"
        "/receipt:preview"
    ),
    openapi_extra=PREVIEW_OPENAPI_EXTRA,
    summary="Preview Receipt",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def preview_receipt(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    registration_uid: ULID,
    payload: GenerateReceiptRequest,
) -> HttpResponse:
    """Preview a receipt without saving.

    Compiles the provided typst template with registration context and returns the
    resulting PDF bytes directly.
    """
    __, ___, pdf_bytes, ____ = await _resolve_and_compile_receipt(
        conference_name,
        registration_uid,
        payload.template,
        payload.extra_context,
    )
    return HttpResponse(pdf_bytes, content_type="application/pdf")


GET_RECEIPT_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
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
) -> HttpResponse | StreamingHttpResponse:
    """Retrieve the rendered receipt for a registration."""
    receipt = await aget_object_or_404(Receipt, registration__uid=uid)
    try:
        return build_file_download_response(
            receipt.rendered_pdf,
            filename="receipt.pdf",
            content_type="application/pdf",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise Http404 from exc


@router.get(
    "/conferences/-/registrations/{ulid:uid}/receipt/{str:filename}",
    openapi_extra=GET_RECEIPT_OPENAPI_EXTRA,
    summary="Get Receipt",
    auth=None,
)
async def get_receipt_ex(
    request: HttpRequest,
    uid: ULID,
    filename: str,  # noqa: ARG001
) -> HttpResponse | StreamingHttpResponse:
    """Retrieve the rendered receipt with a decorative filename segment."""
    return await get_receipt(request, uid)


class ReceiptResponse(Schema):
    registration_uid: ULID
    registration_reference_code: str
    extra: dict[str, Any]
    create_time: AwareDatetime
    update_time: AwareDatetime

    @staticmethod
    def resolve_registration_uid(receipt: Receipt) -> ULID:
        return cast(ULID, receipt.registration.uid)

    @staticmethod
    def resolve_registration_reference_code(receipt: Receipt) -> str:
        return receipt.registration.reference_code

    @staticmethod
    def resolve_extra(receipt: Receipt) -> dict[str, Any]:
        return cast(dict[str, Any], receipt.context.get("extra", {}))


@router.get(
    "/conferences/{slug:conference_name}/registrations/-/receipt",
    response=list[ReceiptResponse],
    summary="List Receipts",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def list_receipts(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> list[Receipt]:
    """List all receipts for a conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return [
        receipt
        async for receipt in Receipt.objects.filter(
            registration__conference=conference
        ).select_related("registration")
    ]

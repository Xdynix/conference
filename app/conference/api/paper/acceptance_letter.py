import asyncio
import json
from http import HTTPStatus
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    AcceptanceLetter,
    Conference,
    ConferenceRole,
    IEEEeCopyrightConfig,
    Paper,
    PaperState,
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

from .core import PaperDetailResponse, prefetch_paper, router

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


class GenerateAcceptanceLetterRequest(Schema):
    template: str = Field(min_length=1, max_length=500_000)


async def _resolve_and_compile_letter(
    conference_name: str,
    paper_code: str,
    template: str,
) -> tuple[Conference, Paper, bytes, dict[str, Any]]:
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active()
        .select_related("conference", "track", "owner__profile")
        .prefetch_related("authors"),
        code=paper_code,
    )

    if paper.withdraw_time is not None:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Cannot generate acceptance letter for withdrawn paper."),
        )

    accepted_states = {PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED}
    if paper.state not in accepted_states:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Cannot generate acceptance letter for paper in state '{state}'.").format(
                state=paper.state,
            ),
        )

    ieee_ecopyright_required = (
        await IEEEeCopyrightConfig.objects.filter(conference_id=paper.conference_id)
        .exclude(exempt_tracks=paper.track)
        .aexists()
    )

    owner_profile = getattr(paper.owner, "profile", None)
    context: dict[str, Any] = {
        "conference": {
            "name": paper.conference.name,
            "display_name": paper.conference.display_name,
            "start_date": paper.conference.start_date,
            "end_date": paper.conference.end_date,
            "location": paper.conference.location,
        },
        "track": {
            "display_name": paper.track.display_name,
            "ieee_ecopyright_required": ieee_ecopyright_required,
        },
        "paper": {
            "code": paper.code,
            "title": paper.title,
            "user": {
                "given_name": getattr(owner_profile, "given_name", ""),
                "family_name": getattr(owner_profile, "family_name", ""),
                "affiliation": getattr(owner_profile, "affiliation", ""),
                "region_code": getattr(owner_profile, "region_code", ""),
                "region_name": Region.get_label(
                    getattr(owner_profile, "region_code", "")
                ),
                "email": paper.owner.email,
            },
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
        },
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

    return conference, paper, pdf_bytes, context


@router.post(
    (
        "/conferences/{slug:conference_name}/papers/{slug:paper_code}"
        "/acceptance-letter:generate"
    ),
    response={
        HTTPStatus.OK: PaperDetailResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Generate Acceptance Letter",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def generate_acceptance_letter(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: GenerateAcceptanceLetterRequest,
) -> Paper:
    """Generate an acceptance letter for a paper.

    Compiles the provided typst template with paper context and stores the resulting
    PDF. Regenerating replaces any existing letter.
    """
    user = await request.auser()
    conference, paper, pdf_bytes, context = await _resolve_and_compile_letter(
        conference_name,
        paper_code,
        payload.template,
    )

    @sync_to_async
    def save_letter() -> None:
        with transaction.atomic():
            old_pdf_name = (
                AcceptanceLetter.objects.filter(paper=paper)
                .values_list("rendered_pdf", flat=True)
                .first()
            )

            letter, __ = AcceptanceLetter.objects.update_or_create(
                paper=paper,
                defaults={"template": payload.template, "context": context},
            )
            letter.rendered_pdf.save(
                "acceptance-letter.pdf",
                ContentFile(pdf_bytes),
                save=False,
            )
            letter.save(update_fields=["rendered_pdf"])

            if old_pdf_name and old_pdf_name != letter.rendered_pdf.name:
                storage = letter.rendered_pdf.storage
                transaction.on_commit(lambda: storage.delete(old_pdf_name))

    await save_letter()

    await audit(
        request=request,
        action=AuditAction.PAPER_GENERATE_ACCEPTANCE_LETTER,
        resource=paper,
        scope=conference.name,
        payload=payload,
        detail={"context": context},
    )

    return await prefetch_paper(conference, paper, user, request)


@router.post(
    (
        "/conferences/{slug:conference_name}/papers/{slug:paper_code}"
        "/acceptance-letter:preview"
    ),
    openapi_extra=PREVIEW_OPENAPI_EXTRA,
    summary="Preview Acceptance Letter",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def preview_acceptance_letter(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    paper_code: str,
    payload: GenerateAcceptanceLetterRequest,
) -> HttpResponse:
    """Preview an acceptance letter without saving.

    Compiles the provided typst template with paper context and returns the resulting
    PDF bytes directly.
    """
    __, ___, pdf_bytes, ____ = await _resolve_and_compile_letter(
        conference_name, paper_code, payload.template
    )
    return HttpResponse(pdf_bytes, content_type="application/pdf")


GET_ACCEPTANCE_LETTER_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    }
}


@router.get(
    "/conferences/-/papers/{ulid:uid}/acceptance-letter",
    openapi_extra=GET_ACCEPTANCE_LETTER_OPENAPI_EXTRA,
    summary="Get Acceptance Letter",
    auth=None,
)
async def get_acceptance_letter(
    request: HttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Retrieve the rendered acceptance letter for a paper."""
    letter = await aget_object_or_404(AcceptanceLetter, paper__uid=uid)
    try:
        return build_file_download_response(
            letter.rendered_pdf,
            filename="acceptance-letter.pdf",
            content_type="application/pdf",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise Http404 from exc


@router.get(
    "/conferences/-/papers/{ulid:uid}/acceptance-letter/{str:filename}",
    openapi_extra=GET_ACCEPTANCE_LETTER_OPENAPI_EXTRA,
    summary="Get Acceptance Letter",
    auth=None,
)
async def get_acceptance_letter_ex(
    request: HttpRequest,
    uid: ULID,
    filename: str,  # noqa: ARG001
) -> HttpResponse | StreamingHttpResponse:
    """Retrieve the rendered acceptance letter with a decorative filename segment."""
    return await get_acceptance_letter(request, uid)

from http import HTTPStatus

from django.http import HttpRequest, HttpResponse
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
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
    Paper,
    PaperState,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import PaperDetailResponse, prefetch_paper, router

# TODO: Add PDF generation for acceptance letters. Current gap: HTML to PDF conversion
#  requires either OS-level libraries (xhtml2pdf, WeasyPrint with system deps) or a
#  headless browser (Playwright, Puppeteer), with no elegant pure Python solution.
#
# TODO: Add acceptance letter email sending endpoint.
#
# TODO: Add endpoint to upload externally generated PDF to be sent with the email, as a
#  workaround until PDF generation is implemented.

jinja_env = SandboxedEnvironment(
    autoescape=True,
    undefined=StrictUndefined,
)


class GenerateAcceptanceLetterRequest(Schema):
    template: str = Field(min_length=1, max_length=500_000)


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

    Renders the provided Jinja2 template with paper context and stores the result.
    Regenerating replaces any existing letter.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active()
        .select_related("conference", "track__conference", "owner__profile")
        .prefetch_related("authors", "keywords"),
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

    try:
        jinja_env.parse(payload.template)
    except TemplateSyntaxError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    try:
        rendered_html = jinja_env.from_string(payload.template).render(paper=paper)
    except UndefinedError as exc:
        raise make_validation_error(path="template", message=str(exc)) from exc

    await AcceptanceLetter.objects.aupdate_or_create(
        paper=paper,
        defaults={"rendered_html": rendered_html},
    )

    await audit(
        request=request,
        action=AuditAction.PAPER_GENERATE_ACCEPTANCE_LETTER,
        resource=paper,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_paper(conference, paper, user, request)


GET_ACCEPTANCE_LETTER_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {"text/html": {"schema": {"type": "string"}}},
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
) -> HttpResponse:
    """Retrieve the rendered acceptance letter for a paper."""
    letter = await aget_object_or_404(AcceptanceLetter, paper__uid=uid)
    return HttpResponse(letter.rendered_html, content_type="text/html")

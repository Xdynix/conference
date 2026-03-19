from http import HTTPStatus
from typing import Annotated, Any, Literal
from urllib.parse import urljoin

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import CharField, QuerySet, Value
from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from jinja2 import UndefinedError
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from pydantic import AwareDatetime, BeforeValidator, Field, HttpUrl, StringConstraints
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, PaperProof
from app.conference.services import ProofService
from app.conference.services.proof import (
    ProofEligibilityError,
    ProofNotifyEmailContext,
    RecipientDerivationError,
    SendProofNotifyResult,
    SendProofNotifyStatus,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error
from app.utils.email import EmailTemplate, RenderedEmail
from app.utils.files import UploadValidationError, build_file_download_response
from app.utils.sanitization import sanitize_formatted_text

router = Router(tags=["Proof"], exclude_none=True)


class ProofResponse(Schema):
    uid: ULID
    paper_code: str
    paper_title: str
    recipient_name: str
    recipient_email: str
    confirmed_time: AwareDatetime | None
    comment: str
    comment_time: AwareDatetime | None
    notification_time: AwareDatetime | None
    proof_url: HttpUrl
    file_url: HttpUrl | None
    create_time: AwareDatetime
    update_time: AwareDatetime

    @staticmethod
    def resolve_paper_code(proof: PaperProof) -> str:
        return proof.paper.code

    @staticmethod
    def resolve_paper_title(proof: PaperProof) -> str:
        return proof.paper.title

    @staticmethod
    def resolve_proof_url(proof: PaperProof) -> HttpUrl:
        base_url: str = proof.base_url  # type: ignore[attr-defined]
        path = reverse("frontend:paper-proof", args=[proof.uid])
        return HttpUrl(urljoin(base_url, path))

    @staticmethod
    def resolve_file_url(proof: PaperProof) -> HttpUrl | None:
        if not proof.file:
            return None
        base_url: str = proof.base_url  # type: ignore[attr-defined]
        path = reverse("api-1.0.0:download-proof-file", args=[proof.uid])
        return HttpUrl(urljoin(base_url, path))


def with_proof_prefetch(
    queryset: QuerySet[PaperProof],
    request: HttpRequest,
) -> QuerySet[PaperProof]:
    """Apply select_related and URL annotations for proof serialization."""
    return queryset.select_related("paper").annotate(
        base_url=Value(
            request.build_absolute_uri("/"),
            output_field=CharField(),
        ),
    )


async def prefetch_proof(proof: PaperProof, request: HttpRequest) -> PaperProof:
    """Refetch a proof with all related data prefetched for serialization."""
    qs = with_proof_prefetch(PaperProof.objects.all(), request)
    return await qs.aget(pk=proof.pk)


@router.get(
    "/conferences/{slug:conference_name}/papers/-/proof",
    response=list[ProofResponse],
    summary="List Proofs",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def list_proofs(
    request: AuthedHttpRequest,
    conference_name: str,
) -> list[PaperProof]:
    """List all proofs for a conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    qs = with_proof_prefetch(
        PaperProof.objects.filter(paper__conference=conference),
        request,
    )
    return [proof async for proof in qs]


class UpsertProofRequest(Schema):
    recipient_name: str = ""
    recipient_email: EmailStr | Literal[""] = ""


@router.put(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/proof",
    response={
        HTTPStatus.OK: ProofResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Upsert Proof",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def upsert_proof(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: UpsertProofRequest,
) -> PaperProof:
    """Create or update a proof record for a paper.

    Auto-derives recipient fields from the corresponding author or paper owner when not
    explicitly provided.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    paper = await aget_object_or_404(
        conference.papers.active().select_related(
            "owner__profile",
            "track__conference",
        ),
        code=paper_code,
    )

    try:
        proof = await sync_to_async(ProofService.upsert)(
            paper,
            recipient_name=payload.recipient_name,
            recipient_email=payload.recipient_email,
        )
    except ProofEligibilityError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except RecipientDerivationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_PROOF_UPSERT,
        resource=proof,
        scope=conference.name,
        payload=payload,
    )

    return await prefetch_proof(proof, request)


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/proof:upload",
    response=ProofResponse,
    summary="Upload Proof File",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def upload_proof_file(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    file: File[UploadedFile],
) -> PaperProof:
    """Upload a proof PDF for a paper.

    The proof record must already exist (create it via PUT first). If replacing an
    existing file, confirmation state is reset.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )
    proof = await aget_object_or_404(
        PaperProof.objects.select_related("paper__track__conference"),
        paper=paper,
    )

    try:
        proof = await sync_to_async(ProofService.upload)(
            proof,
            file,
            max_size=settings.MAX_PROOF_SIZE,
            allowed_types=settings.ALLOWED_PROOF_TYPES,
        )
    except UploadValidationError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit(
        request=request,
        action=AuditAction.PAPER_PROOF_UPLOAD,
        resource=proof,
        scope=conference.name,
        payload={"file": {"name": file.name or "", "size": file.size or 0}},
    )

    return await prefetch_proof(proof, request)


class EmailTemplateRequest(EmailTemplate, Schema):
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)


class PreviewProofNotifyRequest(EmailTemplateRequest):
    pass


class PreviewProofNotifyResponse(RenderedEmail, Schema):
    pass


@router.post(
    "/conferences/{slug:conference_name}/papers/-/proof:preview-notify",
    response={
        HTTPStatus.OK: PreviewProofNotifyResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Preview Proof Notification Email",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def preview_proof_notify(
    request: AuthedHttpRequest,
    conference_name: str,  # noqa: ARG001
    payload: PreviewProofNotifyRequest,
) -> RenderedEmail:
    """Render a proof notification email template with sample context.

    Returns a preview of the email that would be sent. Uses placeholder context data
    so the admin can verify the template before sending.
    """
    base_url = request.build_absolute_uri("/")
    sample_context = ProofNotifyEmailContext.sample(base_url=base_url)

    try:
        return payload.render(sample_context)
    except UndefinedError as exc:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


class SendProofNotifyRequest(EmailTemplateRequest):
    proofs: list[ULID] = Field(min_length=1, max_length=100)


class SendProofNotifyResponse(Schema):
    results: list[SendProofNotifyResult]


@router.post(
    "/conferences/{slug:conference_name}/papers/-/proof:notify",
    response={
        HTTPStatus.OK: SendProofNotifyResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Send Proof Notifications",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def send_proof_notify(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: SendProofNotifyRequest,
) -> dict[str, Any]:
    """Send proof notification emails to the specified proofs.

    Validates that all provided UIDs belong to the conference. Each proof is processed
    independently; proofs without an uploaded file are skipped.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    existing_uids = {
        uid
        async for uid in PaperProof.objects.filter(
            paper__conference=conference,
            uid__in=payload.proofs,
        ).values_list("uid", flat=True)
    }

    requested_uids = set(payload.proofs)
    missing_uids = requested_uids - existing_uids
    if missing_uids:
        message = _("Some proof UIDs do not exist: {uids}").format(
            uids=", ".join(str(uid) for uid in sorted(missing_uids))
        )
        raise make_validation_error(path="proofs", message=message)

    base_url = request.build_absolute_uri("/")
    results = await sync_to_async(ProofService.send_notifications)(
        list(requested_uids),
        template=payload,
        base_url=base_url,
    )

    status_counts = {status.value: 0 for status in SendProofNotifyStatus}
    for result in results:
        status_counts[result.status] += 1

    await audit(
        request=request,
        action=AuditAction.PAPER_PROOF_NOTIFY,
        resource=AuditResource.PAPER_PROOF,
        scope=conference.name,
        payload=payload,
        detail={
            "targeted_count": len(payload.proofs),
            **status_counts,
        },
    )

    return {"results": results}


class AuthorProofResponse(Schema):
    paper_code: str
    paper_title: str
    confirmed_time: AwareDatetime | None
    comment: str
    comment_time: AwareDatetime | None
    proof_url: HttpUrl
    file_url: HttpUrl | None

    @staticmethod
    def resolve_paper_code(proof: PaperProof) -> str:
        return proof.paper.code

    @staticmethod
    def resolve_paper_title(proof: PaperProof) -> str:
        return proof.paper.title

    @staticmethod
    def resolve_proof_url(proof: PaperProof) -> HttpUrl:
        base_url: str = proof.base_url  # type: ignore[attr-defined]
        path = reverse("frontend:paper-proof", args=[proof.uid])
        return HttpUrl(urljoin(base_url, path))

    @staticmethod
    def resolve_file_url(proof: PaperProof) -> HttpUrl | None:
        if not proof.file:
            return None
        base_url: str = proof.base_url  # type: ignore[attr-defined]
        path = reverse("api-1.0.0:download-proof-file", args=[proof.uid])
        return HttpUrl(urljoin(base_url, path))


@router.get(
    "/conferences/-/paper-proofs/{ulid:uid}",
    response=AuthorProofResponse,
    summary="Get Proof",
    auth=None,
)
async def get_proof(
    request: HttpRequest,
    uid: ULID,
) -> PaperProof:
    """Retrieve proof details for a paper."""
    qs = with_proof_prefetch(PaperProof.objects.all(), request)
    return await aget_object_or_404(qs, uid=uid)


@router.post(
    "/conferences/-/paper-proofs/{ulid:uid}:confirm",
    response=AuthorProofResponse,
    summary="Confirm Proof",
    auth=None,
)
async def confirm_proof(
    request: HttpRequest,
    uid: ULID,
) -> PaperProof:
    """Confirm that the proof is acceptable. Idempotent."""
    proof = await aget_object_or_404(
        PaperProof.objects.select_related(
            "paper__conference",
            "paper__track__conference",
        ),
        uid=uid,
    )

    proof = await sync_to_async(ProofService.confirm)(proof)

    await audit(
        request=request,
        action=AuditAction.PAPER_PROOF_CONFIRM,
        resource=proof,
        scope=proof.paper.conference.name,
    )

    return await prefetch_proof(proof, request)


ProofComment = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]


class CommentProofRequest(Schema):
    comment: ProofComment


@router.post(
    "/conferences/-/paper-proofs/{ulid:uid}:comment",
    response=AuthorProofResponse,
    summary="Add Proof Comment",
    auth=None,
)
async def comment_proof(
    request: HttpRequest,
    uid: ULID,
    payload: CommentProofRequest,
) -> PaperProof:
    """Add or update a comment on the proof."""
    proof = await aget_object_or_404(
        PaperProof.objects.select_related(
            "paper__conference",
            "paper__track__conference",
        ),
        uid=uid,
    )

    proof = await sync_to_async(ProofService.comment)(proof, payload.comment)

    await audit(
        request=request,
        action=AuditAction.PAPER_PROOF_COMMENT,
        resource=proof,
        scope=proof.paper.conference.name,
        payload=payload,
    )

    return await prefetch_proof(proof, request)


DOWNLOAD_FILE_OPENAPI_EXTRA = {
    "responses": {
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    }
}


@router.get(
    "/conferences/-/paper-proofs/{ulid:uid}/file",
    openapi_extra=DOWNLOAD_FILE_OPENAPI_EXTRA,
    summary="Download Proof File",
    auth=None,
)
async def download_proof_file(
    request: HttpRequest,  # noqa: ARG001
    uid: ULID,
) -> HttpResponse | StreamingHttpResponse:
    """Download the proof PDF for a paper."""
    proof = await aget_object_or_404(
        PaperProof.objects.select_related("paper"),
        uid=uid,
    )
    if not proof.file:
        raise Http404
    try:
        return build_file_download_response(
            proof.file,
            filename=f"{proof.paper.code}-proof.pdf",
            content_type="application/pdf",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise Http404 from exc

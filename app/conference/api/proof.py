from http import HTTPStatus
from typing import Literal
from urllib.parse import urljoin

from asgiref.sync import sync_to_async
from django.db.models import CharField, QuerySet, Value
from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from django.urls import reverse
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import AwareDatetime, HttpUrl
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, PaperProof
from app.conference.services import ProofService
from app.conference.services.proof import (
    ProofEligibilityError,
    RecipientDerivationError,
)
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse
from app.utils.files import build_file_download_response

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

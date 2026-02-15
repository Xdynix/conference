from django.shortcuts import aget_object_or_404
from ninja import Field, Schema

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole
from app.conference.services import PaperService
from app.conference.types import PaperCode
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


class AnnouncePapersRequest(Schema):
    codes: list[PaperCode] = Field(default_factory=list, max_length=500)


@router.post(
    "/conferences/{slug:conference_name}/papers:announce",
    response=list[PaperCode],
    summary="Announce Papers",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def announce_papers(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: AnnouncePapersRequest,
) -> list[str]:
    """Announce decisions for multiple papers.

    Sets the announcement timestamp on eligible papers. A paper is eligible if it has
    a decision, is not withdrawn, is not already announced, and has an acceptance
    letter (for accepted papers only). Returns the codes of papers that were announced.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    announced_codes = await PaperService.announce_papers(conference, payload.codes)

    await audit(
        request=request,
        action=AuditAction.PAPER_ANNOUNCE,
        resource=AuditResource.PAPER,
        scope=conference.name,
        payload=payload,
        detail={
            "requested_count": len(payload.codes),
            "announced_count": len(announced_codes),
        },
    )

    return announced_codes

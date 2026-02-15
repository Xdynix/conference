from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


@router.delete(
    "/conferences/{slug:conference_name}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Conference",
    auth=has_any_roles(GlobalRole.ADMIN),
)
async def delete_conference(
    request: AuthedHttpRequest,
    conference_name: str,
) -> tuple[int, None]:
    """Delete a conference."""
    try:
        conference = await sync_to_async(ConferenceService.deactivate_conference)(
            name=conference_name
        )
    except Conference.DoesNotExist as exc:
        raise Http404 from exc

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_DELETE,
        resource=conference,
        scope=conference.name,
    )

    return HTTPStatus.NO_CONTENT, None

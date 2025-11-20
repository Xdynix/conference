from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import get_object_or_404
from loguru import logger

from app.conference.models import Conference
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


@transaction.atomic
def deactivate_conference(conference_name: str) -> Conference:
    conference = get_object_or_404(
        Conference.objects.active().select_for_update(),
        name=conference_name,
    )
    conference.active = False
    conference.save(update_fields=["active", "update_time"])
    return conference


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
    conference = await sync_to_async(deactivate_conference)(conference_name)

    user = await request.auser()
    logger.info("Conference deleted.", conference=conference, user=user)

    return HTTPStatus.NO_CONTENT, None

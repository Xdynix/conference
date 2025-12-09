from django.shortcuts import aget_object_or_404
from ninja import Router, Schema
from pydantic import AwareDatetime
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import CodePool, Conference, ConferenceRole
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

router = Router(tags=["Code Pool"], exclude_none=True)


class CodePoolResponse(Schema):
    uid: ULID
    name: str
    prefix: str
    next_sequence: int
    create_time: AwareDatetime
    update_time: AwareDatetime


@router.get(
    "/conferences/{slug:conference_name}/code-pools",
    response=list[CodePoolResponse],
    summary="List Code Pools",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def list_code_pools(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> list[CodePool]:
    """Return all code pools for the conference."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return [pool async for pool in conference.code_pools.order_by("prefix")]

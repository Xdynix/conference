from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from loguru import logger
from ninja import Field, PatchDict, Schema

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, ConferenceVisibility
from app.conference.services import ConferenceService, KeywordService
from app.conference.types import ConferenceDisplayName, KeywordSetName, KeywordText
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import ConferenceDetailResponse, prefetch_conference, router


class ConferenceSchema(Schema):
    display_name: ConferenceDisplayName
    keywords: list[KeywordText] = Field(max_length=500)
    keyword_sets: list[KeywordSetName] = Field(max_length=50)
    visibility: ConferenceVisibility


@router.patch(
    "/conferences/{slug:conference_name}",
    response={
        HTTPStatus.OK: ConferenceDetailResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update Conference",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_conference(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: PatchDict[ConferenceSchema],
) -> Conference:
    """Update conference attributes.

    Global admins can update any conference. Conference chairs can update only their
    assigned conference.
    """
    try:
        keywords = await KeywordService.validate_keyword_texts(
            payload.get("keywords")  # type: ignore[func-returns-value]
        )
    except ValueError as exc:
        raise make_validation_error(path="keywords", message=str(exc)) from exc

    try:
        keyword_sets = await KeywordService.validate_keyword_set_names(
            payload.get("keyword_sets")  # type: ignore[func-returns-value]
        )
    except ValueError as exc:
        raise make_validation_error(path="keyword_sets", message=str(exc)) from exc

    try:
        conference = await sync_to_async(ConferenceService.update_conference)(
            name=conference_name,
            display_name=payload.get("display_name"),
            visibility=payload.get("visibility"),
            keywords=keywords,
            keyword_sets=keyword_sets,
        )
    except Conference.DoesNotExist as exc:
        raise Http404 from exc

    user = await request.auser()
    logger.info(
        "Conference updated.",
        conference_name=conference.name,
        user_uid=user.uid,
    )

    return await prefetch_conference(conference, user)

from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import get_object_or_404
from loguru import logger
from ninja import PatchDict, Schema

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Keyword
from app.conference.services import ConferenceService
from app.conference.types import ConferenceDetail, ConferenceDisplayName, KeywordSetName
from app.conference.types import Keyword as KeywordText
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import router, validate_keyword_payload


class ConferenceSchema(Schema):
    display_name: ConferenceDisplayName
    keywords: list[KeywordText]
    keyword_sets: list[KeywordSetName]
    visibility: Conference.Visibility


@transaction.atomic
def patch_conference(
    conference_name: str,
    payload: PatchDict[ConferenceSchema],
) -> Conference:
    conference = get_object_or_404(
        Conference.objects.active().select_for_update(),
        name=conference_name,
    )

    update_fields: list[str] = []
    if "display_name" in payload:
        conference.display_name = payload["display_name"]
        update_fields.append("display_name")
    if "visibility" in payload:
        conference.visibility = payload["visibility"]
        update_fields.append("visibility")

    keywords_provided = "keywords" in payload
    keyword_sets_provided = "keyword_sets" in payload
    keywords_updated = keywords_provided or keyword_sets_provided
    if keywords_updated:  # pragma: no branch
        keywords, keyword_sets = validate_keyword_payload(
            keyword_texts=payload.get("keywords", []),
            keyword_set_names=payload.get("keyword_sets", []),
        )
        assigned_keywords: set[Keyword] = set()
        assigned_keywords.update(keywords)
        for keyword_set in keyword_sets:
            assigned_keywords.update(keyword_set.keywords.all())
        conference.keywords.set(assigned_keywords)

    if update_fields or keywords_updated:  # pragma: no branch
        conference.save(update_fields=[*update_fields, "update_time"])

    return conference


@router.patch(
    "/conferences/{slug:conference_name}",
    response={
        HTTPStatus.OK: ConferenceDetail,
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
    user = await request.auser()
    conference = await sync_to_async(patch_conference)(conference_name, payload)

    logger.info("Conference updated.", conference=conference, user=user)

    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=conference.pk,
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return conference

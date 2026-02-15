from datetime import date
from http import HTTPStatus
from typing import Literal

from asgiref.sync import sync_to_async
from django.http import Http404
from ninja import Field, PatchDict, Schema
from pydantic import ValidationInfo, field_validator

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, ConferenceVisibility
from app.conference.services import ConferenceService, KeywordService
from app.conference.types import (
    ConferenceDisplayName,
    ConferenceInstructions,
    ConferenceLocation,
    KeywordSetName,
    KeywordText,
)
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
    registration_enabled: bool
    start_date: date | Literal[""]
    end_date: date | Literal[""]
    location: ConferenceLocation
    paper_submission_instructions: ConferenceInstructions
    paper_final_instructions: ConferenceInstructions

    @field_validator("end_date")
    @classmethod
    def _validate_end_date(
        cls,
        v: date | Literal[""],
        info: ValidationInfo,
    ) -> date | Literal[""]:
        start_date = info.data["start_date"]
        if v == "" or start_date == "":
            return v
        if v < start_date:
            raise ValueError("End date must be on or after start date.")
        return v


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
            registration_enabled=payload.get("registration_enabled"),
            keywords=keywords,
            keyword_sets=keyword_sets,
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            location=payload.get("location"),
            paper_submission_instructions=payload.get("paper_submission_instructions"),
            paper_final_instructions=payload.get("paper_final_instructions"),
        )
    except Conference.DoesNotExist as exc:
        raise Http404 from exc

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_UPDATE,
        resource=conference,
        scope=conference.name,
        payload=payload,
    )

    user = await request.auser()
    return await prefetch_conference(conference, user)

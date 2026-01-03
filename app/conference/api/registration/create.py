from http import HTTPStatus
from typing import Annotated, Literal

from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from pydantic import StringConstraints
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Paper,
    Registration,
    RegistrationState,
    RegistrationTitle,
)
from app.conference.services import ConferenceService
from app.conference.types import (
    Affiliation,
    FamilyName,
    GivenName,
    PaperCode,
    RegionCode,
    RegistrationPhone,
    RegistrationReceiptTitle,
    RegistrationSelfIntroduction,
)
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import UserRegistrationResponse, prefetch_registration, router


class CreateMyRegistrationRequest(Schema):
    paper: PaperCode | None = None
    attendance_type: ULID
    receipt_title: Annotated[
        RegistrationReceiptTitle,
        StringConstraints(min_length=1),
    ]
    title: RegistrationTitle | Literal[""] = ""
    given_name: Annotated[
        GivenName,
        StringConstraints(min_length=1),
    ]
    family_name: Annotated[
        FamilyName,
        StringConstraints(min_length=1),
    ]
    affiliation: Annotated[
        Affiliation,
        StringConstraints(min_length=1),
    ]
    region_code: RegionCode
    # Using `EmailStr` instead of `VerifiedEmailStr`: verification is intentionally
    # skipped because it's common for one person to register on behalf of another (e.g.,
    # a student filling the form for a professor). Requiring verification would create
    # poor UX in delegation scenarios.
    email: EmailStr
    phone: Annotated[
        RegistrationPhone,
        StringConstraints(min_length=1),
    ]
    self_introduction: Annotated[
        RegistrationSelfIntroduction,
        StringConstraints(min_length=1),
    ]


@router.post(
    "/conferences/{slug:conference_name}/my-registrations",
    response={
        HTTPStatus.CREATED: UserRegistrationResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create My Registration",
    auth=is_authenticated,
)
async def create_my_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: CreateMyRegistrationRequest,
) -> tuple[int, Registration]:
    """Creates a new registration for the current user.

    The registration is created in pending state, awaiting payment. A unique reference
    code is generated for matching offline payments. If the selected attendance type
    requires a paper, one must be provided from the announced accepted papers.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    if not conference.registration_enabled:
        raise HttpError(
            HTTPStatus.FORBIDDEN,
            _("Registration is not currently open for this conference."),
        )

    try:
        attendance_type = await conference.attendance_types.filter(
            admin_only=False
        ).aget(uid=payload.attendance_type)
    except AttendanceType.DoesNotExist as exc:
        raise make_validation_error(
            path="attendance_type",
            message=_("Invalid attendance type."),
        ) from exc

    # TODO: Currently any user can register for any announced paper without authorship
    #  verification. This could allow someone to claim a paper they didn't author. We
    #  intentionally keep this open because: (1) paper author lists may be incomplete
    #  for imported papers, (2) registrants may not know what emails were used. Consider
    #  adding owner-only restriction or admin review workflow if abuse becomes a
    #  concern.
    paper: Paper | None = None
    if payload.paper is not None:
        if not attendance_type.paper_required:
            raise make_validation_error(
                path="paper",
                message=_("This attendance type does not allow paper selection."),
            )
        try:
            paper = await conference.papers.registrable().aget(code=payload.paper)
        except Paper.DoesNotExist as exc:
            raise make_validation_error(
                path="paper",
                message=_("Paper not found or not available for registration."),
            ) from exc
    elif attendance_type.paper_required:
        raise make_validation_error(
            path="paper",
            message=_("This attendance type requires a paper selection."),
        )

    registration = await Registration.objects.acreate(
        conference=conference,
        state=RegistrationState.PENDING,
        user=user,
        paper=paper,
        attendance_type=attendance_type,
        receipt_title=payload.receipt_title,
        title=payload.title,
        given_name=payload.given_name,
        family_name=payload.family_name,
        affiliation=payload.affiliation,
        region_code=payload.region_code,
        email=payload.email,
        phone=payload.phone,
        self_introduction=payload.self_introduction,
    )

    logger.info(
        "Registration created.",
        registration_uid=str(registration.uid),
        reference_code=registration.reference_code,
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return HTTPStatus.CREATED, await prefetch_registration(registration)

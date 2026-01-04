from http import HTTPStatus
from typing import Annotated, Literal

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import PatchDict, Schema
from ninja.errors import HttpError
from pydantic import StringConstraints
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    AttendanceType,
    Conference,
    ConferenceRole,
    Registration,
    RegistrationTitle,
)
from app.conference.services import ConferenceService, RegistrationService
from app.conference.services.registration import (
    AttendanceTypeIncompatibleError,
    InvalidRegistrationStateError,
)
from app.conference.types import (
    Affiliation,
    FamilyName,
    GivenName,
    RegionCode,
    RegistrationPhone,
    RegistrationReceiptTitle,
    RegistrationSelfIntroduction,
)
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest, EmailStr
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import (
    RegistrationResponse,
    UserRegistrationResponse,
    prefetch_registration,
    router,
)


class RegistrationSchema(Schema):
    receipt_title: Annotated[
        RegistrationReceiptTitle,
        StringConstraints(min_length=1),
    ]
    title: RegistrationTitle | Literal[""]
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


@router.patch(
    "/conferences/{slug:conference_name}/my-registrations/{ulid:registration_uid}",
    response={
        HTTPStatus.OK: UserRegistrationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Update My Registration",
    auth=is_authenticated,
)
async def update_my_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
    payload: PatchDict[RegistrationSchema],
) -> Registration:
    """Updates a registration owned by the current user.

    Only registrations in pending state can be updated. Paper and attendance type are
    immutable. All fields are optional; omitted fields retain their existing values.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    registration = await aget_object_or_404(
        conference.registrations.filter(user=user),
        uid=registration_uid,
    )

    try:
        updated = await sync_to_async(RegistrationService.update_registration)(
            registration,
            mode="author",
            **payload,
        )
    except InvalidRegistrationStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Registration updated.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_registration(updated)


class AdminRegistrationSchema(RegistrationSchema):
    attendance_type: ULID


@router.patch(
    "/conferences/{slug:conference_name}/registrations/{ulid:registration_uid}",
    response={
        HTTPStatus.OK: RegistrationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Update Registration",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def update_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
    payload: PatchDict[AdminRegistrationSchema],
) -> Registration:
    """Updates a registration as an admin.

    Registrations in pending or confirmed state can be updated. Paper is immutable but
    attendance type can be changed if compatible with the registration's paper presence.
    All fields are optional; omitted fields retain their existing values.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    registration = await aget_object_or_404(
        conference.registrations.all(),
        uid=registration_uid,
    )

    try:
        updated = await sync_to_async(RegistrationService.update_registration)(
            registration,
            mode="admin",
            **payload,
        )
    except InvalidRegistrationStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    except AttendanceType.DoesNotExist as exc:
        raise make_validation_error(
            path="attendance_type",
            message=_("Invalid attendance type."),
        ) from exc
    except AttendanceTypeIncompatibleError as exc:
        raise make_validation_error(
            path="attendance_type",
            message=str(exc),
        ) from exc

    logger.info(
        "Registration updated by admin.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return await prefetch_registration(updated)

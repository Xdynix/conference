from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import Conference, ConferenceRole, Registration
from app.conference.services import ConferenceService, RegistrationService
from app.conference.services.registration import InvalidRegistrationStateError
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import (
    RegistrationResponse,
    UserRegistrationResponse,
    prefetch_registration,
    router,
)


@router.post(
    "/conferences/{slug:conference_name}/my-registrations/{ulid:registration_uid}:cancel",
    response={
        HTTPStatus.OK: UserRegistrationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Cancel My Registration",
    auth=is_authenticated,
)
async def cancel_my_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
) -> Registration:
    """Cancels a registration owned by the current user.

    Only registrations in pending state can be cancelled.
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
        cancelled = await sync_to_async(RegistrationService.cancel_registration)(
            registration,
            mode="author",
        )
    except InvalidRegistrationStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Registration cancelled.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_registration(cancelled)


@router.post(
    "/conferences/{slug:conference_name}/registrations/{ulid:registration_uid}:cancel",
    response={
        HTTPStatus.OK: RegistrationResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
    },
    summary="Cancel Registration",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def cancel_registration(
    request: AuthedHttpRequest,
    conference_name: str,
    registration_uid: ULID,
) -> Registration:
    """Cancels a registration as an admin.

    Registrations in pending or confirmed state can be cancelled.
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
        cancelled = await sync_to_async(RegistrationService.cancel_registration)(
            registration,
            mode="admin",
        )
    except InvalidRegistrationStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Registration cancelled by admin.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        admin_uid=str(user.uid),
    )

    return await prefetch_registration(cancelled)

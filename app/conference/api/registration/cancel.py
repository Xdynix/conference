from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from loguru import logger
from ninja.errors import HttpError
from ulid import ULID

from app.conference.models import Registration
from app.conference.services import ConferenceService, RegistrationService
from app.conference.services.registration import InvalidRegistrationStateError
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse

from .core import UserRegistrationResponse, prefetch_registration, router


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
            registration
        )
    except InvalidRegistrationStateError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    logger.info(
        "Registration cancelled.",
        registration_uid=str(registration.uid),
        conference_name=conference.name,
        user_uid=str(user.uid),
    )

    return await prefetch_registration(cancelled, request)

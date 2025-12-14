from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, assert_never

from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Schema
from ninja.errors import HttpError
from pydantic import Field
from ulid import ULID

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import Conference, ConferenceRole, Track, TrackRole
from app.conference.services import RoleAssignmentService
from app.conference.services.conference import InsufficientRolePermission
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import RoleAssignmentResponse, router, with_role_assignment_prefetch


class MutateAction(StrEnum):
    ADD_CONFERENCE_ROLE = "add_conference_role"
    REMOVE_CONFERENCE_ROLE = "remove_conference_role"
    ADD_TRACK_ROLE = "add_track_role"
    REMOVE_TRACK_ROLE = "remove_track_role"


class ConferenceRoleAction(Schema):
    action: Literal[
        MutateAction.ADD_CONFERENCE_ROLE,
        MutateAction.REMOVE_CONFERENCE_ROLE,
    ]
    role: ConferenceRole


class TrackRoleAction(Schema):
    action: Literal[
        MutateAction.ADD_TRACK_ROLE,
        MutateAction.REMOVE_TRACK_ROLE,
    ]
    track: ULID
    role: TrackRole


MutateRoleAssignmentRequest = Annotated[
    ConferenceRoleAction | TrackRoleAction,
    Field(discriminator="action"),
]


@router.post(
    "/conferences/{slug:conference_name}/role-assignments/{ulid:user_uid}:mutate",
    response={
        HTTPStatus.OK: RoleAssignmentResponse,
        HTTPStatus.FORBIDDEN: ErrorResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Mutate Role Assignment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def mutate_role_assignment(
    request: AuthedHttpRequest,
    conference_name: str,
    user_uid: ULID,
    payload: MutateRoleAssignmentRequest,
) -> User:
    """Add or remove a single role for a user in the conference.

    This endpoint performs a single role mutation operation (add or remove) for a
    specified user. Operations are idempotent: adding an existing role or removing a
    missing role succeeds silently without error.

    - **Global admins**: Can perform all actions on any conference.
    - **Conference chairs**: Can perform all actions within their conference.
    - **Conference secretaries**: Can only add or remove the `Reviewer` and `Member`
      roles (for both conference and track roles).
    - **Track chairs**: Can only perform track actions on tracks they administer.
    - **Track secretaries**: Can only add or remove the `Reviewer` and `Member` roles
      for tracks they administer.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    target_user = await aget_object_or_404(
        User.objects.active(),
        uid=user_uid,
    )

    try:
        match payload.action:
            case MutateAction.ADD_CONFERENCE_ROLE:
                await sync_to_async(RoleAssignmentService.add_conference_role)(
                    conference=conference,
                    target_user=target_user,
                    role=payload.role,
                    requesting_user=user,
                )
            case MutateAction.REMOVE_CONFERENCE_ROLE:
                await sync_to_async(RoleAssignmentService.remove_conference_role)(
                    conference=conference,
                    target_user=target_user,
                    role=payload.role,
                    requesting_user=user,
                )
            case MutateAction.ADD_TRACK_ROLE:
                track = await Track.objects.active().aget(
                    uid=payload.track,
                    conference=conference,
                )
                await sync_to_async(RoleAssignmentService.add_track_role)(
                    conference=conference,
                    track=track,
                    target_user=target_user,
                    role=payload.role,
                    requesting_user=user,
                )
            case MutateAction.REMOVE_TRACK_ROLE:
                track = await Track.objects.active().aget(
                    uid=payload.track,
                    conference=conference,
                )
                await sync_to_async(RoleAssignmentService.remove_track_role)(
                    conference=conference,
                    track=track,
                    target_user=target_user,
                    role=payload.role,
                    requesting_user=user,
                )
            case _ as unreachable:
                assert_never(unreachable)
    except ValueError as exc:
        raise make_validation_error(path="track", message=str(exc)) from exc
    except InsufficientRolePermission as exc:
        raise HttpError(HTTPStatus.FORBIDDEN, str(exc)) from exc
    except Track.DoesNotExist as exc:
        raise make_validation_error(
            path="track",
            message=_("Invalid track UID."),
        ) from exc

    logger.info(
        "Role assignment mutated.",
        action=payload.action,
        conference_name=conference.name,
        target_user_uid=target_user.uid,
        requesting_user_uid=user.uid,
        role=payload.role,
        track_uid=payload.track if isinstance(payload, TrackRoleAction) else None,
    )

    qs = await with_role_assignment_prefetch(
        User.objects.active(),
        conference=conference,
        requesting_user=user,
    )
    return await qs.aget(uid=user_uid)


# Design note:
# This endpoint is intentionally RPC-style (`:mutate`) with a discriminated union
# payload instead of four REST-style endpoints (POST/DELETE for conference roles and
# track roles). The choice targets admin UX:
# - One mutation hook and a small action enum keep the frontend simple and strongly
#   typed via OpenAPI.
# - The underlying services still model pure CRUD on role assignments; the RPC surface
#   is an API ergonomics layer, not a domain change.
# - Adding parallel RESTful endpoints later would be straightforward without touching
#   these services or the existing admin flow.
# Example RESTful alternative (could live alongside if ever needed):
#   POST   /conferences/{slug}/users/{user_uid}/conference-roles
#       body: {"role": "..."}
#   DELETE /conferences/{slug}/users/{user_uid}/conference-roles/{role}
#   POST   /conferences/{slug}/tracks/{track_uid}/users/{user_uid}/roles
#       body: {"role": "..."}
#   DELETE /conferences/{slug}/tracks/{track_uid}/users/{user_uid}/roles/{role}

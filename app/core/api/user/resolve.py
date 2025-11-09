from typing import Annotated, Literal, assert_never

from loguru import logger
from ninja import Field, Schema
from ulid import ULID

from app.core.auth import has_permissions
from app.core.models import User
from app.core.types import EmailStr, HttpRequest, Username

from .core import router


class ResolveUserByUsernameRequest(Schema):
    by: Literal["username"]
    username: Username


class ResolveUserByEmailRequest(Schema):
    by: Literal["email"]
    email: EmailStr


ResolveUserRequest = Annotated[
    ResolveUserByUsernameRequest | ResolveUserByEmailRequest,
    Field(discriminator="by"),
]


class ResolveUserResponse(Schema):
    uid: ULID | None


@router.post(
    "/users:resolve",
    response=ResolveUserResponse,
    summary="Resolve User UID",
    auth=has_permissions(User.READ),
)
async def resolve_user(
    request: HttpRequest,  # noqa: ARG001
    payload: ResolveUserRequest,
) -> ResolveUserResponse:
    """Resolve a user identifier to a ULID.

    Converts a natural user identifier (`username` or `email`) into the user's immutable
    UID. The request specifies the identifier type in the `by` field and provides
    exactly one corresponding value. Useful for translating login-style identifiers into
    stable IDs for use in other API requests.
    """
    match payload:
        case ResolveUserByUsernameRequest():
            query = User.objects.filter(is_active=True, username=payload.username)
        case ResolveUserByEmailRequest():
            query = User.objects.filter(is_active=True, email__iexact=payload.email)
        case _ as unreachable:
            assert_never(unreachable)

    try:
        user = await query.values("uid").aget()
    except User.DoesNotExist:
        return ResolveUserResponse(uid=None)
    except User.MultipleObjectsReturned:  # pragma: no cover
        logger.error(
            "Resolve user got multiple results, which should never happen.",
            payload=payload,
        )
        raise

    return ResolveUserResponse(uid=user["uid"])

from datetime import datetime
from http import HTTPStatus

from asgiref.sync import sync_to_async
from django.http import Http404
from django.utils.translation import gettext as _
from ninja import Router, Schema

from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
from app.core.auth import is_authenticated
from app.core.models import ApiKey
from app.core.services.api_key import ApiKeyService
from app.core.types import AuthedHttpRequest, Password
from app.ninja.errors import ErrorResponse, make_validation_error

router = Router(tags=["API Key"], exclude_none=True)


class CreateApiKeyRequest(Schema):
    password: Password


class CreateApiKeyResponse(Schema):
    key: str
    create_time: datetime


@router.post(
    "/api-keys",
    response={
        HTTPStatus.OK: CreateApiKeyResponse,
        HTTPStatus.UNPROCESSABLE_ENTITY: ErrorResponse,
    },
    summary="Create API Key",
    auth=is_authenticated,
)
async def create_api_key(
    request: AuthedHttpRequest,
    payload: CreateApiKeyRequest,
) -> CreateApiKeyResponse:
    """Create or rotate the caller's API key.

    Requires the current password. If an active key already exists, it is revoked and
    its sessions are deleted before the new key is created. The plaintext key is
    returned once and cannot be retrieved again.
    """
    user = await request.auser()

    if not await user.acheck_password(payload.password.get_secret_value()):
        raise make_validation_error(
            path="password",
            message=_("Invalid password."),
        )

    api_key, plaintext = await sync_to_async(ApiKeyService.create_key)(user)

    await audit(
        request=request,
        action=AuditAction.API_KEY_CREATE,
        resource=AuditResource.API_KEY,
        resource_id=str(api_key.pk),
        payload=payload,
    )

    return CreateApiKeyResponse(key=plaintext, create_time=api_key.create_time)


class ApiKeyResponse(Schema):
    create_time: datetime
    last_use_time: datetime | None


@router.get(
    "/api-keys/current",
    response=ApiKeyResponse,
    summary="Get Current API Key",
    auth=is_authenticated,
)
async def get_current_api_key(request: AuthedHttpRequest) -> ApiKey:
    """Return metadata about the caller's active API key.

    Returns 404 if no active key exists. The plaintext key is never included.
    """
    user = await request.auser()

    api_key = await sync_to_async(ApiKeyService.get_current_key)(user)
    if api_key is None:
        raise Http404

    return api_key


@router.delete(
    "/api-keys/current",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Revoke Current API Key",
    auth=is_authenticated,
)
async def delete_current_api_key(
    request: AuthedHttpRequest,
) -> tuple[int, None]:
    """Revoke the caller's active API key and delete its linked sessions.

    Succeeds silently if no active key exists.
    """
    user = await request.auser()

    api_key = await sync_to_async(ApiKeyService.revoke_key)(user)

    if api_key is not None:
        await audit(
            request=request,
            action=AuditAction.API_KEY_REVOKE,
            resource=AuditResource.API_KEY,
            resource_id=str(api_key.pk),
        )

    return HTTPStatus.NO_CONTENT, None

"""Audit log writer for mutation API endpoints.

Each mutation endpoint calls ``audit()`` explicitly rather than relying on middleware.
Middleware cannot reliably identify the affected resource or capture business context
(e.g. the UID of a newly created instance, state before a transition) because that
information lives in the view, not in URL patterns or request/response bytes.

The unit of logging is the API request, not the affected resource. Batch operations
(e.g. sending invitations) produce one row with batch details in ``payload`` and/or
``detail``; ``resource_id`` is left empty when there is no single target. Nested
creation (e.g. conference with tracks) produces one row for the parent; nested data is
in the payload. Individual sub-resource endpoints produce their own rows.

Sensitive fields (passwords, tokens) are safe to pass in ``payload`` as long as they are
typed as Pydantic's ``SecretStr``, which serializes to a masked value in
``model_dump(mode="json")``.

The ``audit()`` call happens in the API layer after the service method (and its
transaction) returns. If the business operation fails, the exception propagates before
``audit()`` is reached, so no phantom records are created. If ``audit()`` itself fails,
the business data is already committed; the failure is logged and swallowed.
"""

from typing import Any

from django.http import HttpRequest
from loguru import logger
from pydantic import BaseModel

from app.audit.models import AuditLog
from app.audit.types import Auditable, AuditAction, AuditResource
from app.core.models import User
from app.utils.orjson import serializer as json_serializer


async def audit(
    *,
    request: HttpRequest,
    action: AuditAction,
    resource: Auditable | AuditResource,
    resource_id: str = "",
    resource_label: str = "",
    scope: str = "",
    payload: dict[str, Any] | BaseModel | None = None,
    detail: dict[str, Any] | None = None,
    actor: User | None = None,
) -> None:
    """Record an audit log entry for a mutation API endpoint.

    Logs the action to both the database and the application logger. The actor is
    resolved from the request when not provided explicitly. Pass ``actor`` for endpoints
    that change the session user (e.g. logout, assume, revert).

    Pass ``resource`` as an ``Auditable`` model instance to extract resource metadata
    automatically, or as an ``AuditResource`` enum with explicit ``resource_id`` and
    ``resource_label`` for resources without a model (e.g. sessions, password resets) or
    batch operations.

    Pass ``payload`` as a dict or a Pydantic ``BaseModel``. Models are serialized via
    ``model_dump(mode="json")``.

    Exceptions are swallowed and logged so a failed audit write never breaks the
    business response.
    """
    try:
        if isinstance(resource, Auditable):
            info = resource.audit_resource_info()
            resource_type = info["resource"]
            resource_id = info["resource_id"]
            resource_label = info["resource_label"]
        else:
            resource_type = resource

        if actor is None:
            user = await request.auser()
            if user.is_authenticated:
                actor = user

        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        elif isinstance(payload, dict):
            payload = json_serializer.loads(json_serializer.dumps(payload))

        actor_uid = str(actor.uid) if actor else ""
        actor_label = (actor.email or actor.username) if actor else ""

        logger.info(
            "audit: {action} {resource} {resource_id} by {actor}",
            action=action,
            resource=resource_type,
            resource_id=resource_id,
            actor=actor_label or actor_uid or "anonymous",
        )

        api_key_label = getattr(request, "api_key_label", "")
        extra_detail: dict[str, Any] = {}
        if api_key_label:
            extra_detail["api_key"] = api_key_label

        await AuditLog.objects.acreate(
            action=action,
            resource=resource_type,
            resource_id=resource_id,
            resource_label=resource_label,
            scope=scope,
            actor_uid=actor_uid,
            actor_label=actor_label,
            payload=payload or {},
            detail={**(detail or {}), **extra_detail},
            ip_address=getattr(request, "client_ip", None),
            request_id=getattr(request, "request_id", ""),
        )
    except Exception:
        logger.exception("Failed to write audit log entry.")

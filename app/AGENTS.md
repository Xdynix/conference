# Backend Guidelines

Conventions for Python under `app/`: API endpoints, services, authorization, audit
logging, and background jobs.

## Architecture Principles

### API and Schema Standards

- Align interface design, resource shapes, and model field naming (including timestamps)
  with Google AIP conventions.
- Django's built-in user fields keep their framework names (`is_active`,
  `is_authenticated`, `is_superuser`, etc.) as the sole exception.

### API Naming and URL Resolution

The project uses a customized Django Ninja setup (`app/ninja/core.py`) that converts
function names to kebab-case for URL names:

- **Function naming**: Use `snake_case` for API view functions (e.g., `submit_my_paper`,
  `get_my_paper`, `create_draft`).
- **URL name generation**: Functions are automatically converted to kebab-case URL names
  (e.g., `submit_my_paper` -> `api-1.0.0:submit-my-paper`).

**Finding endpoint URL names**:

1. Locate the API function in `app/<app>/api.py` or `app/<app>/api/`.
2. Note the function name (e.g., `delete_my_paper`).
3. The URL name is `api-1.0.0:{function-name-in-kebab-case}` (e.g.,
   `api-1.0.0:delete-my-paper`).
4. Test files in `tests/conference/api/` often have helper methods showing URL patterns.

### Async-First Design

- Prefer async views, API endpoints, and background tasks.
- Use Django's async ORM methods (`acreate`, `aget`, `aupdate`, `adelete`, `acount`,
  `aexists`).
- Write async-compatible middleware and utilities.
- Use async context managers and iterators where appropriate.

### Async/Sync Boundaries and Transactions

Django's transaction primitives (`transaction.atomic`, `select_for_update`, etc.) are
sync-only. Keep transactional logic synchronous and insert a single context switch at
the request boundary so ORM behavior stays predictable.

**Key principles**:

- **Keep transactions sync**: Methods that own a transaction must be synchronous. This
  allows Django to manage the connection correctly and keeps nested transactions safe.
- **Switch once at the edge**: Async API views should call transactional operations with
  `sync_to_async()` so only one hop occurs.
- **Enable sync reuse**: When operations remain sync, other sync code paths (signals,
  Django admin, management commands) can reuse them without extra wrappers.

**Example pattern**:

```python
# services.py - transactional work stays sync
from django.db import transaction


class MyService:
    @classmethod
    @transaction.atomic()
    def transactional_operation(cls, user: User) -> None:
        user.refresh_from_db()
        Related.objects.create(user=user)


# api.py - async boundary does the context switch
from asgiref.sync import sync_to_async


@router.post("/endpoint")
async def my_endpoint(request: AuthedHttpRequest) -> dict[str, str]:
    user = await request.auser()
    await sync_to_async(MyService.transactional_operation)(user)
    return {"status": "ok"}
```

**Antipattern**: Never stack `@sync_to_async` on top of `@transaction.atomic()`.

### Row Locking and the Mutex Primitive

Django's `select_for_update()` has **no effect on SQLite**. It does not acquire any
locks. This means code relying on it for serialization will have race conditions during
development and testing (which use SQLite).

Use the `Mutex` primitive from `app.infra.models` instead. It provides database-backed
distributed locking that works on both PostgreSQL (using `SELECT FOR UPDATE`) and SQLite
(using write transactions that serialize writers).

**Example pattern**:

```python
from app.infra.models import Mutex


class MyService:
    @classmethod
    def update_with_lock(cls, resource_id: str) -> None:
        with Mutex.lock_in_transaction(resource_id, namespace="my_resource"):
            resource = Resource.objects.get(pk=resource_id)
            # ... modify resource ...
            resource.save()
```

**Key points**:

- `Mutex.lock_in_transaction()` opens its own `transaction.atomic()`, so you don't need
  the decorator.
- The `namespace` parameter prevents key collisions across different resource types.
- The lock is held until the transaction commits.
- Never use `select_for_update()` directly in service code; always prefer `Mutex`.

**Namespace and key selection**:

- Use a **shared namespace** when the same logical resource is modified from multiple
  apps. For example, `user_role_assignments` is used in both `core` (global roles) and
  `conference` (conference/track roles) because they all guard modifications to a user's
  role assignments.
- Within the same namespace, always use a **consistent key format**. If one method uses
  `str(invitation.uid)`, all methods in that namespace must use `uid`. Never mix `pk`,
  `uid`, and `name`. Inconsistent keys create separate locks that don't block each
  other.

**Multiple locks and ordering**:

When acquiring multiple mutexes in one operation, always acquire them in a consistent
order across the codebase to avoid deadlocks. For example, if `redeem_invitation` locks
`invitation` then `user_role_assignments`, any other operation that needs both locks
must use the same order. Document the expected order when introducing new multi-lock
patterns.

```python
# Correct: consistent order (invitation -> user_role_assignments)
with (
    Mutex.lock_in_transaction(str(invitation.uid), namespace="invitation"),
    Mutex.lock_in_transaction(str(user.pk), namespace="user_role_assignments"),
):
    ...
```

### File Cleanup

`django-cleanup` automatically deletes orphaned files when a model instance is deleted
(including bulk `QuerySet.delete()` and CASCADE), or when a `FileField` value is
replaced on save. It uses Django signals and defers file removal to
`transaction.on_commit()`, so rollbacks are safe.

**Limitations to keep in mind when writing new code:**

- **Only `FileField` and `ImageField` are tracked.** Never store file paths in
  `CharField`, `TextField`, `JSONField`, or any other field type. If a file needs to be
  referenced, use a `FileField`.
- **No shared files across instances.** `django-cleanup` assumes each file belongs to
  exactly one model instance. Never copy a `FileField` value from one instance to
  another; always save a new copy of the file instead.

## Service Layer

The service layer contains all business logic and remains completely decoupled from HTTP
concerns. Services should never import or use `HttpError`, `HttpRequest`, HTTP status
codes, or request/response schemas. Instead, services return domain objects or raise
domain-specific exceptions (e.g., `ValueError`, custom exceptions), and views translate
these results into appropriate HTTP responses with status codes.

- **Service Classes**: Use for multistep operations, transactional logic, or
  functionality shared across contexts (API views, background jobs, management commands,
  Django admin).
- **Module Helpers**: Use small module-level functions for localized operations within a
  single module.
- **Inline View Logic**: Keep code in views only when trivial (1-2 lines) and specific
  to one endpoint.
- **View Responsibilities**: Parse HTTP requests, call services, catch service
  exceptions, and translate results to `HttpError` responses.

## Authorization

The application uses layered authorization with roles at three scopes.

### Role Hierarchy

**Superuser** (`User.is_superuser`): Bypasses all permission checks unconditionally.

**Global roles** (`GlobalRole` in `app/core/models.py`): Platform-wide, not scoped to
any conference.

- **ADMIN** - Platform operator. Full read/write access across all conferences.
- **READ_ALL** - Auditor/observer. Cross-conference read access without write
  privileges.

Both are treated as "globally privileged" and receive full conference scope.

**Conference roles** (`ConferenceRole` in `app/conference/models/role.py`): Scoped to
one conference via `ConferenceRoleAssignment`.

- **CHAIR** - The authority. Full administrative access, including the ability to
  delegate admin power (assign any role, including Chair/Secretary).
- **SECRETARY** - Operational admin. Same access as Chair for day-to-day operations, but
  cannot escalate privileges (can only assign Reviewer/Member).
- **REVIEWER** - Subject-matter expert. Participates in the review process but has no
  administrative access.
- **MEMBER** - Basic participant. Grants visibility into member-only resources. No admin
  or review privileges.

**Track roles** (`TrackRole` in `app/conference/models/role.py`): Same four roles as
conference level, but scoped to a single track via `TrackRoleAssignment`. Track admins
get scope over their tracks only, not the full conference.

Both role enums provide grouping helpers: `admins()` returns [CHAIR, SECRETARY];
`reviewers()` returns [CHAIR, SECRETARY, REVIEWER].

### Two-Layer Enforcement

**Layer 1 - API gate**: The `auth=` parameter on each endpoint controls entry using
composable `SessionAuth` instances. Two modules provide guards:

`app/core/auth.py` - global guards:

- `is_authenticated` - any active, logged-in user. Use when further scoping happens at
  layer 2 (e.g., "list my papers").
- `has_any_roles(GlobalRole.ADMIN)` - global admins only (superusers always pass).
- `has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)` - admins or read-all users.
- Combine with `&` (all required) or `|` (any sufficient) for composed guards.

`app/conference/auth.py` - conference-scoped guards that resolve the conference from URL
path parameters and check conference or track roles. Most conference endpoints use
these. Use global guards only for platform-wide endpoints (user management, sessions) or
when combined with conference guards via `|`.

**Layer 2 - data scoping**: Services use `ConferenceAccessService.context()` to build a
`ConferenceAccessContext` and filter querysets by the user's effective scope.

-> Implementation: `app/core/auth.py`, `app/conference/auth.py`,
`app/conference/services/access.py`.

### ConferenceAccessContext Pattern

`ConferenceAccessService.context()` resolves a user's effective privileges for a
conference into a frozen dataclass with these key fields:

- `has_full_conference_scope` - `True` when the user is globally privileged (superuser
  or global admin/read-all) or a conference admin (CHAIR or SECRETARY). Grants access to
  all tracks.
- `administered_track_ids` - tracks where the user is a track CHAIR or SECRETARY. Only
  populated when `has_full_conference_scope` is `False`.

The default `global_roles` includes READ_ALL. Mutation endpoints must narrow it to
`(GlobalRole.ADMIN,)`; read paths pass their `global_readable` roles through.

Services use this to scope querysets:

```python
ctx = await ConferenceAccessService.context(
    conference=conference, user=user, global_roles=(GlobalRole.ADMIN,)
)
if ctx.has_full_conference_scope:
    return papers
if not ctx.administered_track_ids:
    return papers.none()
return papers.filter(track_id__in=ctx.administered_track_ids)
```

-> Usage: `app/conference/services/paper.py`, `app/conference/services/review.py`.

### Role Assignment Permissions

Who can assign which roles (enforced by `ConferenceService.validate_can_assign_roles`):

| Assigner                 | Conference roles | Track roles                   |
|--------------------------|------------------|-------------------------------|
| Superuser / Global Admin | Any              | Any                           |
| Conference Chair         | Any              | Any                           |
| Conference Secretary     | REVIEWER, MEMBER | REVIEWER, MEMBER              |
| Track Chair              | None             | Any (own tracks)              |
| Track Secretary          | None             | REVIEWER, MEMBER (own tracks) |

-> Implementation: `app/conference/services/conference.py`.

### Input Sanitization

User-facing text fields in request schemas use `BeforeValidator` with sanitization
functions from `app/utils/sanitization.py`. Define constrained type aliases in the app's
`types.py` and reuse them across schemas:

```python
from pydantic import BeforeValidator, StringConstraints
from typing import Annotated
from app.utils.sanitization import sanitize_text, sanitize_formatted_text

# Single-line text (titles, names, keywords)
KeywordText = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(min_length=1, max_length=100),
]

# Multi-line text (abstracts, descriptions, comments)
PaperAbstract = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]
```

-> Example: `app/conference/types.py`.

## Schema Design

- Resolver methods (`resolve_{field_name}`) belong only in response or request schemas,
  never in shared base schemas in `types.py` because they prevent reuse across contexts.
- For response schemas that need computed fields, create a separate response schema that
  inherits from the base schema and adds the resolver methods.
- Place response schemas with resolver methods in `core.py` when shared across multiple
  endpoints, or define them inline in `api.py` when endpoint-specific.
- See `app/conference/types.py` for examples, particularly `Invitation` which composes
  base schemas (`UserConferenceProfile`, `Profile`) without resolvers.
- Enums the frontend reads must be registered in `enums_json()`
  (`app/frontend/templatetags/frontend_tags.py`).

### Response Prefetch Pattern

Complex responses often require prefetching related data to avoid N+1 queries. Define
prefetch helpers that annotate querysets with computed fields:

```python
async def with_paper_prefetch(queryset: QuerySet[Paper], ...) -> QuerySet[Paper]:
    return queryset.select_related(...).annotate(...).prefetch_related(...)
```

Call prefetch helpers before returning paginated or detailed objects.

-> Example: `with_paper_prefetch` in `app/conference/api/paper/core.py`.

## Error Handling

### API Error Handling

- Use Django Ninja's `HttpError` in API views only (never in services) for translating
  business logic errors into HTTP responses with appropriate status codes.
- All user-facing error messages must use `gettext` for internationalization: `_("Error
  message")`. This is future-proofing; there is no active translation workflow.
- Never expose internal error details, stack traces, or sensitive information to
  clients.
- The centralized exception handler in `app/ninja/errors.py` converts all exceptions to
  consistent `ErrorResponse` schemas.

### Validation Errors

Use `make_validation_error()` for business logic validation that should return
field-level errors:

```python
from app.ninja.errors import make_validation_error

if not track or track.conference_id != conference.pk:
    raise make_validation_error(
        path="track",
        message=_("Invalid track UID."),
    )
```

### Exception Chaining

Always chain exceptions with `from exc` to preserve the original traceback:

```python
except PaperStateError as exc:
    raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
```

### Logging Practices

- Use loguru logger (`from loguru import logger`) for unexpected errors, warnings, and
  diagnostics that don't fit the audit log (e.g., infrastructure issues, background job
  progress).
- Use appropriate log levels: `logger.info()` for operations, `logger.warning()` for
  suspicious conditions, `logger.error()` for errors, `logger.exception()` for caught
  exceptions.
- Do not add `logger.info()` calls for successful mutations in API views or services;
  the audit log covers these. The `audit()` helper emits its own structured log line.

## Audit Logging

All mutation API endpoints must call `audit()` from `app.audit.services` to record who
did what. The audit helper writes to both the database and the application logger, so no
separate `logger.info()` is needed for audited actions.

**Imports**:

```python
from app.audit.services import audit
from app.audit.types import AuditAction, AuditResource
```

**Adding new resources and actions**: Add enum members to `AuditResource` and
`AuditAction` in `app/audit/types.py`. These are plain `StrEnum` (no migration needed).
Actions follow `resource.verb` naming (e.g., `paper.submit`, `user.set_password`).
Resource members and action sections are alphabetical.

**Basic call pattern**:

```python
await audit(
    request=request,
    action=AuditAction.PAPER_SUBMIT,
    resource=paper,  # Auditable instance; extracts metadata automatically
    scope=conference.name,  # conference-scoped; omit for global endpoints
    payload=payload,  # BaseModel or dict; auto-serialized
)
```

**With explicit resource metadata** (when the model doesn't implement `Auditable`):

```python
await audit(
    request=request,
    action=AuditAction.USER_CREATE,
    resource=AuditResource.USER,
    resource_id=str(user.uid),
    resource_label=user.email or user.username,
    payload=payload,
)
```

**Key conventions**:

- **Scope**: Pass `scope=conference.name` for conference-scoped endpoints. Global
  endpoints (user management, sessions, password reset) omit it.
- **Resource ID**: Always `str(instance.uid)` for ULID-based models. Batch operations
  emit one entry with the `AuditResource` enum as `resource`, no resource ID, and counts
  in `detail`.
- **Payload**: Pass the request payload directly. `SecretStr` fields (passwords)
  serialize as masked values automatically. Omit when the payload only contains data
  already captured in resource metadata.
- **Detail**: Use for results, outcomes, and side effects that aren't part of the
  request input (e.g., `detail={"state_before": previous_state}`,
  `detail={"sent_count": 5}`).
- **Actor**: Resolved from `request.auser()` automatically. Only pass `actor=`
  explicitly when the endpoint changes the session user (logout, assume, revert).
- **Failed attempts**: Security-relevant failures (e.g., failed login, invitation
  conflict) should be audited with a dedicated `_FAILED` action (e.g.,
  `SESSION_CREATE_FAILED`, `INVITATION_REDEEM_FAILED`).

**Auditable mixin**: Models frequently passed to `audit()` should implement `Auditable`
from `app/audit/types.py` to centralize resource metadata. Do not add `Auditable` to
models in foundational packages (`app/core/`) to avoid circular dependencies; pass
`AuditResource` enum explicitly instead.

## API View Conventions

- **Naming**: Use imperative snake_case verbs that mirror the HTTP method (
  `get_session`, `create_password_reset`, `verify_email_verification`). For RPC-style
  routes that use colon suffixes, keep the verb specific to the action (
  `assume_session`, `revert_session`).
- **Summary**: Keep `summary=` short, title-cased, and reader-facing (for example, "Get
  Session", "Issue Code", "Start Impersonation"). This appears as the primary label in
  generated API docs.
- **Docstrings**: Begin with a clear prose description aimed at API consumers and omit
  Google-style sections so the text renders cleanly in the documentation.

## Background Jobs

The project uses APScheduler (`BackgroundScheduler`) for periodic tasks. The shared
scheduler instance lives in `app/infra/services.py`, and the `runscheduler` management
command (`app/infra/management/commands/runscheduler.py`) starts it as a long-running
process.

### Job Auto-Discovery

At startup, `runscheduler` iterates all installed Django apps and imports each app's
`.jobs` module (suppressing `ModuleNotFoundError` for apps that don't have one). This
import triggers `@scheduler.scheduled_job(...)` decorators, which register the jobs with
the scheduler.

### Adding a New Job

1. Create or open `jobs.py` in the target app (e.g., `app/conference/jobs.py`).
2. Import the scheduler and decorate the function:

   ```python
   from app.infra.services import scheduler


   @scheduler.scheduled_job("cron", hour="*/6", jitter=120)
   def my_periodic_task() -> None: ...
   ```

3. The job will be picked up automatically on the next `runscheduler` start; no
   registration boilerplate is needed.

### Conventions

- Keep job functions focused; delegate complex logic to service methods.
- Use `jitter` to spread execution when exact timing is not critical.
- Jobs run outside Django's request-response cycle, so database connections are cleaned
  up automatically by a listener in `app/infra/services.py`.

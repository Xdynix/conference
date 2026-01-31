# Backend Guidelines

This document defines backend implementation patterns for the project.

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
async def my_endpoint(request: HttpRequest) -> dict[str, str]:
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

## Schema Design

- Resolver methods (`resolve_{field_name}`) belong only in response or request schemas,
  never in shared base schemas in `types.py` because they prevent reuse across contexts.
- For response schemas that need computed fields, create a separate response schema that
  inherits from the base schema and adds the resolver methods.
- Place response schemas with resolver methods in `core.py` when shared across multiple
  endpoints, or define them inline in `api.py` when endpoint-specific.
- See `app/conference/types.py` for examples, particularly `Invitation` which composes
  base schemas (`UserConferenceProfile`, `Profile`) without resolvers.

### Response Prefetch Pattern

Complex responses often require prefetching related data to avoid N+1 queries. Define
prefetch helpers that annotate querysets with computed fields:

```python
async def with_paper_prefetch(queryset: QuerySet[Paper]) -> QuerySet[Paper]:
    return (
        queryset.select_related("conference", "track", "owner__profile")
        .annotate(
            submitted_average=Avg("reviews__recommendation", filter=Q(...)),
            final_count=Count("revisions", filter=Q(is_final=True)),
        )
        .prefetch_related(...)
    )
```

Call prefetch helpers before returning paginated or detailed objects.

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

- Use loguru logger (`from loguru import logger`) throughout the application.
- Log all unexpected errors, important state changes, and security-relevant events.
- Use appropriate log levels: `logger.info()` for operations, `logger.error()` for
  errors, `logger.exception()` for caught exceptions.
- Include structured business context (actor, target, change summary when light):

```python
logger.info(
    "Paper submitted by owner.",
    paper_code=paper.code,
    conference_name=conference.name,
    user_uid=str(user.uid),
)
```

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

## Testing

### Framework and Database Testing

- Use pytest with pytest-django, pytest-asyncio, faker, and pytest-mock.
- Use `pytest-mock`'s `mocker` fixture instead of `unittest.mock.patch`.
- Use `@pytest.mark.django_db` for tests that access the database.
- Prefer synchronous tests whenever the system under test is synchronous; async test
  cases are only needed when the subject itself is async because sync tests are simpler
  and faster.
- If the system under test is async or the test covers transactional behavior (
  `IntegrityError` propagation, rollbacks, `transaction.on_commit`, etc.), mark the test
  function or suite with `transaction=True`.
- Use Django's async ORM methods (`acreate`, `acount`, `aexists`) in async tests.
- Do not add `@pytest.mark.asyncio`; pytest-asyncio handles async tests automatically.

### Test Organization and Best Practices

- **Naming**: Use `test_happy_path` or `test_smoke` for main functionality tests and
  descriptive names for edge cases.
- **Structure**: Create helper factory functions with sensible defaults for test data
  setup.
- **Class-based vs Function-based Tests**: Both function-based and class-based tests are
  acceptable. Use class-based tests when there are several components in the same test
  file that need boundaries between them (e.g., to avoid sharing fixtures or helpers).
  Use function-based tests for simpler, standalone tests.
- **Fixtures**: Use fixtures for common mocks (e.g., `mock_send` fixture for email
  mocking). Only fixtures with truly generic concepts (e.g., global mocks, common API
  clients) should be placed in `conftest.py`. Component-specific or test-class-specific
  fixtures should be defined inline.
- **Docstrings**: Do not add docstrings to test cases if their names are clear enough.
  Docstrings for test helpers are acceptable when they clarify complex setup or
  behavior.
- **Assertions**: Use `tests.helpers.any_*` values for flexible type-based assertions.
- **Code Quality**: Write concise assertions like
  `assert await Model.objects.filter().acount() == 1`.
- **Annotations**: Add `# noqa: ARG002` for intentionally unused fixture parameters.
- **Imports**: Import `MagicMock` from `unittest.mock` for better type hints.

### API Test Pattern

Cover these cases (see `tests/conference/api/conference/test_create.py` for examples):

- Happy path with full response and service call verification.
- Input parsing/sanitization and defaults.
- Validation errors with `loc`/`msg` assertions.
- Service exception -> HTTP response mapping.
- Authorization (unauthenticated, unauthorized, allowed roles).
- Partial updates: "omit keeps existing" and "empty clears value".

### Service Test Pattern

- Test services directly with `@pytest.mark.django_db`.
- Mock external dependencies (email, external APIs) but not the database.
- Test domain exceptions are raised for invalid states.
- See `tests/conference/services/` for examples.

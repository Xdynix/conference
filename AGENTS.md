# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

This is a modern Django 5.2+ application built with Python 3.13+ using async-first
architecture and ASGI deployment. The project uses modern Python and Django features
without concern for backward compatibility. Always use the latest syntax, type hints,
and language features available in Python 3.13+ and Django 5.2+.

## Development Setup

### Required Tools

- **uv** - Python package management (required)
- **just** - Task runner (required)

### Task Runner Commands

All development tasks use `just`:

- `just dev-setup` - Set up development environment (installs deps, pre-commit hooks).
- `just lint` - Run all linters via pre-commit (ruff, mypy, etc.).
- `just test` - Run pytest with coverage (requires 100% coverage).
- `just test <path>` - Run specific tests.
- `just manage <command>` - Django management commands shorthand.
- `just shell` - Start Django shell with shell_plus (IPython).
- `just dev` - Start all development services in parallel.

For quick project-aware experiments, run Python statements through Django's shell
bootstrap so settings and apps load correctly. Example:

```sh
uv run manage.py shell -c \
  "from app.core.models import User; print(User.objects.count())"
```

## Project Structure

The project follows Django's app-based architecture. This structure may evolve over
time, so verify current layout when needed.

### Django Apps

- **`app/core/`** - Core authentication and authorization (user, roles, sessions,
  password reset).
- **`app/conference/`** - Conference-specific domain logic, user profiles, scoped roles,
  and invitations.
- **`app/verikit/`** - User identity verification toolkit (email verification).
- **`app/infra/`** - Infrastructure services (background jobs, scheduling, mutex locks).
- **`app/misc/`** - Miscellaneous utilities and views.
- **`app/admin/`** - Django admin customizations.
- **`app/turnstile/`** - Cloudflare Turnstile demo. Debugging aide that may be removed.

### Shared Modules

- **`app/ninja/`** - Django Ninja utilities (error handlers, JSON serialization, core
  setup).
- **`app/utils/`** - Reusable utilities (throttling, Cloudflare Turnstile decorators,
  custom types, model mixins).
- **`app/api.py`** - Root API router aggregating all app routers.
- **`app/logging.py`** - Loguru logging configuration.

### Common Module Patterns

- **`api.py` or `api/`** - Django Ninja API endpoints with routers and request/response
  schemas.
- **`services.py` or `services/`** - Business logic and service layer.
- **`jobs.py`** - Background job definitions.
- **`types.py`** - Shared Pydantic schemas and rich type aliases.

## Architecture Principles

### Async-First Design

- Prefer async views, API endpoints, and background tasks.
- Use Django's async ORM methods (`acreate`, `aget`, `aupdate`, `adelete`, `acount`,
  `aexists`).
- Write async-compatible middleware and utilities.
- Use async context managers and iterators where appropriate.

#### Async/Sync Boundaries and Transactions

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

**Anti-pattern (avoid)**:

```python
# Never stack @sync_to_async on top of a transactional method.
class MyService:
    @classmethod
    @sync_to_async  # WRONG: wrapper hides sync-only behavior
    @transaction.atomic()
    def transactional_operation(cls, user: User) -> None:
        ...
```

### Schema Design

- Base schemas in `types.py` should not include resolver methods (`resolve_{field_name}`
  static methods) because they prevent the schema from being used in request payloads.
- For response schemas that need computed fields, create a separate response schema that
  inherits from the base schema and adds the resolver methods.
- Place response schemas with resolver methods in `core.py` when shared across multiple
  endpoints, or define them inline in `api.py` when endpoint-specific.

**Example pattern**:

```python
# types.py - base schema without resolvers
class UserSchema(Schema):
    id: UUID
    email: str
    name: str


# core.py or api.py - response schema with resolvers
class UserResponse(UserSchema):
    display_name: str

    @staticmethod
    def resolve_display_name(obj: User) -> str:
        return f"{obj.name} ({obj.email})"
```

### Code Organization

- Follow Django's app-based architecture with clear separation of concerns.
- Keep models focused and use mixins for shared behavior.
- Extract reusable utilities into dedicated modules.
- Use dependency injection patterns for testability.

## Development Standards

### Code Quality and Security

- **Linting**: Configured with ruff (extensive rule set) and mypy (strict mode).
- **Testing**: pytest with 100% code coverage requirement using pytest-django,
  pytest-asyncio, faker, and respx.
- **Pre-commit**: Automatically runs linters and formatters.
- **Type Checking**: Full mypy strict mode with django-stubs.
- **Docstrings**: Use Google Style docstrings for Python functions and classes, except
  API view docstrings that serve the generated API documentation, keep those concise and
  reader-facing instead. Focus docstrings on behavior from the caller's perspective
  rather than implementation details (e.g., "Creates a user" rather than "Inserts a row
  into the users table with a UUID primary key"). Only document side effects when the
  caller needs to be aware of them. Omit the `Args` section when all arguments are
  self-explanatory from their names and types.
- **Dependencies**: Managed with uv and organized into dependency groups (dev, lint,
  test).
- **Security**: SSL/HTTPS configured for development with self-signed certificates and
  extensive security settings (secure cookies, CSRF protection).

### Testing Guidelines

#### Framework and Database Testing

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

#### Test Organization and Best Practices

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

### Error Handling

#### API Error Handling

- Use Django Ninja's `HttpError` in API views only (never in services) for translating
  business logic errors into HTTP responses with appropriate status codes.
- All user-facing error messages must use `gettext` for internationalization: `_("Error
  message")`.
- Never expose internal error details, stack traces, or sensitive information to
  clients.
- The centralized exception handler in `app/ninja/errors.py` converts all exceptions to
  consistent `ErrorResponse` schemas.

#### Exception Chaining and Context

- Always chain exceptions with `from exc` to preserve the original traceback.
    - Example: `raise HttpError(HTTPStatus.CONFLICT, message) from exc`.

#### Service Layer Patterns

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

#### Logging Practices

- Use loguru logger (`from loguru import logger`) throughout the application.
- Log all unexpected errors, important state changes, and security-relevant events.
- Use appropriate log levels: `logger.info()` for operations, `logger.error()` for
  errors, `logger.exception()` for caught exceptions.
- Include structured context in logs: `logger.info("User logged in.", user=user,
  ip=client_ip)`.

### API View Conventions

- **Naming**: Use imperative snake_case verbs that mirror the HTTP method (
  `get_session`, `create_password_reset`, `verify_email_verification`). For RPC-style
  routes that use colon suffixes, keep the verb specific to the action (
  `assume_session`, `revert_session`).
- **Summary**: Keep `summary=` short, title-cased, and reader-facing (for example, "Get
  Session", "Issue Code", "Start Impersonation"). This appears as the primary label in
  generated API docs.
- **Docstrings**: Begin with a clear prose description aimed at API consumers and omit
  Google-style sections so the text renders cleanly in the documentation.

### Writing and Code Style Guidelines

- Follow existing project conventions for formatting, naming, and architecture; ensure
  new code blends seamlessly with surrounding modules.
- Keep natural-language output (logs, error messages, Markdown list items, comments,
  etc.) in complete sentences unless brevity is clearly preferred.
- Do not wrap function parameters unnecessarily: keep them on one line within the
  88-character limit; otherwise, place each argument on its own line ending with a
  comma.
- Prefer `@classmethod` for shared helper methods across the codebase. Reserve
- `@staticmethod` for documented special cases where binding to the class is
  undesirable.
- Keep commit message subjects at or under 50 characters.
- Always request user permission before running the test suite.
- Use the current file content as the baseline for edits; if a user change appears
  problematic, discuss it before reverting.

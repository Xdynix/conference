# Development Guidelines

This file provides guidance to coding agents when working with code in this repository.

## Operational Guidelines

### Interaction Protocol

- **Discussion vs. Action:** Treat user questions involving opinions, feasibility, risk
  assessment, or design exploration (e.g., "Do you think...", "Is it safe...", "How
  should we...") strictly as conversation. Do **not** execute tools that modify files,
  memory, or system state based on these queries.
- **Tests on Demand:** Propose or edit tests freely, but do not execute test commands
  unless the user explicitly asks to run them.
- **Explicit Commands:** Only perform modifications (code changes, file creation, memory
  saves) when the user provides a clear, imperative instruction (e.g., "Implement
  this," "Save that," "Apply the fix").
- **When in Doubt:** If a user's intent is ambiguous between discussion and action,
  provide the analysis first and ask for confirmation before modifying anything.

### Self-Review Protocol

After completing a non-trivial implementation, spawn a challenger subagent to review the
code before presenting it to the user. Skip this for trivial changes (one-liners,
renames, config tweaks) or when the design was already settled through interactive
discussion.

#### Process

1. Implement the change.
2. Spawn a challenger subagent with the task description and the code written.
3. The challenger reviews the code within a single subagent session:
    - If it finds a **clear improvement**, it revises and re-reviews (up to 2 cycles).
    - If it finds **comparable alternatives** with different trade-offs, it stops and
      reports the options instead of choosing one.
4. Incorporate the challenger's findings, then present the final result with a short
   review note summarizing: approach taken, concerns (if any), and alternatives
   considered (if any). Omit the note when there is nothing meaningful to report.

#### Challenger Principles

- **Simplest correct solution.** If the same thing can be done with less code, fewer
  abstractions, or a more obvious approach, prefer that. Never add complexity to handle
  hypothetical futures.
- **Fresh eyes.** Read the code as if you did not write it. Would the intent be clear to
  a new team member? Does the approach feel natural or forced?
- **Fit the codebase.** Check how similar problems are solved nearby. Flag when the
  implementation introduces a new pattern where an existing one would work.
- **Clean code over formatting.** Linters handle spacing, indentation, and import order.
  Focus on what they cannot catch: naming (do names communicate purpose?), organization
  (is logic in the right place?), and abstraction level (does a function mix high-level
  intent with low-level details?).
- **Challenge the "what", not just the "how".** Do not just check code quality. Ask
  whether the approach itself is right. Is there a well-known pattern for this? Could
  this be solved at a different layer?
- **Say nothing when there is nothing to say.** If the implementation is straightforward
  and sound, report that. Do not invent concerns to justify the review.

## Project Overview

A Django 6.0+ application with Python 3.14+, async-first architecture, and ASGI
deployment. The current deployment target is SQLite; application code should remain
database-backend agnostic. The frontend uses Alpine.js with Bootstrap, served via Django
templates (no SPA, no bundlers).

## Backend Development

When working on API endpoints, services, or backend logic, read `.agents/BACKEND.md`.

## Frontend Development

When working on templates, Alpine.js components, or frontend logic, read
`.agents/FRONTEND.md`.

## Business Workflows

When implementing, modifying, or designing features that involve state machines,
multistep user flows, or cross-cutting behavior spanning backend and frontend, read
`WORKFLOWS.md` for the existing states, transitions, actor roles, and step-by-step happy
paths. New workflows should follow the conventions and structure established there.

## Deployment

When working on Docker configuration, nginx, process management, or production settings,
read `.agents/DEPLOYMENT.md`.

## Development Setup

### Required Tools

- **uv** - Python package management (required)
- **just** - Task runner (required)

### Common Commands

- **Run tests**: `uv run pytest <path>` (use `-q` or `-k` as needed). For full-suite
  runs, use `-n auto` for parallel execution via pytest-xdist.
- **Run linters**: `just lint` (runs ruff, mypy via pre-commit)
- **Django management**: `uv run manage.py <command>`
- **Run Python with Django**: `uv run manage.py shell -c "<code>"` (never use
  `python -c` directly; Django apps require proper initialization)
- **First-time setup**: `just dev-setup` (one-time; installs deps, pre-commit hooks)

Humans use `just` commands as shortcuts (e.g., `just test`, `just shell`).

## Project Structure

The project follows Django's app-based architecture.

### Django Apps

- **`app/core/`** - Core authentication and authorization (user, roles, sessions,
  password reset).
- **`app/conference/`** - Conference-specific domain logic, user profiles, scoped roles,
  and invitations.
- **`app/verikit/`** - User identity verification toolkit (email verification).
- **`app/infra/`** - Infrastructure services (background jobs, scheduling, mutex locks).
- **`app/misc/`** - Miscellaneous utilities and views.
- **`app/admin/`** - Custom admin site (login, headers, permissions). Model-specific
  `ModelAdmin` registrations live in each app's own `admin.py` or `admin/` package.
- **`app/audit/`** - Structured audit logging. All mutation API endpoints must call
  `audit()` from this app to record who did what. See the Backend Development guide for
  the call pattern and conventions.
- **`app/frontend/`** - Frontend templates, static files, and views.

When adding new features, choose the appropriate app based on responsibility:

- **Authentication/authorization** (users, sessions, global roles, passwords) -> `core`.
- **Conference domain logic** (profiles, invitations, tracks, scoped roles) ->
  `conference`.
- **Shared infrastructure touching Django** (jobs, scheduling, locks) -> `infra`.
- **Pure utilities without Django dependencies** -> `utils`.
- **UI templates and frontend assets** -> `frontend`.

### Admin Surfaces

The word "admin" refers to two distinct surfaces; do not conflate them.

- **Django admin** - `app/admin/` plus each app's `ModelAdmin` registrations, served at
  `/admin/`. Gated to superusers only (`AdminSite.has_permission`), because fine-grained
  permissions are hard to secure and features like autocomplete can leak data. Use it
  for low-level model CRUD by maintainers, not for conference-scoped admin work.
- **Frontend admin UI** - user-facing conference management built as ordinary frontend
  pages under `app/frontend/templates/frontend/conference/admin/<feature>/`, routed at
  `/<conference_name>/admin/<feature>/` via `protected_view`, and backed by API
  endpoints (for example papers, payments, registrations, guides).

When a request mentions an "admin {feature} page" for conference management, it usually
means the frontend admin UI, not Django admin. Confirm which surface before changing
search, filters, or columns, since each has its own separate implementation.

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
- **`jobs.py`** - Background job definitions (auto-discovered by `runscheduler`).
- **`types.py`** - Shared Pydantic schemas and rich type aliases.

## Code Quality Standards

- **Linting**: Configured with ruff (extensive rule set) and mypy (strict mode). Do not
  run linters or type checkers unless explicitly asked; pre-commit hooks handle this
  automatically on commit.
- **Formatting**: Ruff format runs via `just lint`; rely on it instead of manual
  reflowing beyond the 88-character target.
- **Testing**: pytest with 100% code coverage requirement using pytest-django,
  pytest-asyncio, faker, and respx.
- **Pre-commit**: Automatically runs linters and formatters.
- **Type Checking**: Full mypy strict mode with django-stubs.
- **Dependencies**: Managed with uv and organized into dependency groups (dev, lint,
  test). Add production/runtime deps without a group. Add tooling to the appropriate
  dev group via `uv add --group dev|lint|test <package>`.
- **Migrations**: Create standard Django migrations as needed. Early-stage cleanup or
  squashing may be done by humans; keep migration intent clear and focused.
- **Security**: SSL/HTTPS configured for development with self-signed certificates and
  extensive security settings (secure cookies, CSRF protection).

## Testing

Tests are reviewed by humans before they run. When asked to run tests, prefer
`uv run pytest <path>` (use `-q` or `-k` as needed).

Backend testing patterns (pytest-django, async tests, API/service test coverage) are in
the Backend Development section. Frontend testing will use Playwright when added.

## Full-Stack Coordination

Cross-cutting patterns for features that span backend and frontend.

### Adding a New Enum

1. Define the Python enum in the appropriate app.
2. Add it to `enums_json()` in `app/frontend/templatetags/frontend_tags.py`.
3. Access in frontend via `APP.enums.EnumName.MEMBER.value`.

### Error Contract

- Backend validation errors return 422 with `details` array containing `loc` and `msg`.
- Frontend uses `mapErrors(data.details)` to convert to field-keyed errors.
- Error keys are snake_case (matching API), form fields are camelCase (JS convention).

## Writing and Code Style

- **Modern syntax only**: Use Python 3.14+ and Django 6.0+ features without concern for
  backward compatibility. Use built-in generics (`list[str]`, `dict[str, int]`), union
  syntax (`str | None`), and modern type hints. Never use `from __future__ import`,
  `typing.List`, `typing.Dict`, `typing.Optional`, or `Generic[]` base classes when
  built-in equivalents exist.
- Follow existing project conventions for formatting, naming, and architecture; ensure
  new code blends seamlessly with surrounding modules.
- Keep natural-language output (logs, error messages, Markdown list items, comments,
  etc.) in complete sentences unless brevity is clearly preferred.
- Avoid em dashes entirely; use commas, semicolons, or parentheses instead.
- Do not wrap function parameters unnecessarily: keep them on one line within the
  88-character limit; otherwise, place each argument on its own line ending with a
  comma. Formatters enforce the limit; write code naturally within that boundary.
- Prefer `@classmethod` for shared helper methods across the codebase. Reserve
  `@staticmethod` for documented special cases where binding to the class is undesirable
  (primarily Django Ninja resolver methods per upstream guidance).
- **Comments**: Write self-explanatory code that clearly conveys intent. Do not add
  comments that merely repeat what the code is doing. Only add comments when the intent
  is not explicit from the code itself or to explain design decisions, non-obvious
  behavior, or important context that cannot be expressed through code alone.
- **Docstrings**: Use Google Style docstrings for Python functions and classes, except
  API view docstrings that serve the generated API documentation (keep those concise and
  reader-facing instead). Focus docstrings on behavior from the caller's perspective
  rather than implementation details. Omit the `Args` section when all arguments are
  self-explanatory from their names and types.
- **Commits**: Keep commit message subjects at or under 50 characters. Use conventional
  commit format with type prefix (`feat:`, `fix:`, `refactor:`, etc.) but omit scope.
  Prefer `fix: resolve session expiry` over `fix(core): resolve session expiry`.
- Use the current file content as the baseline for edits; if a user change appears
  problematic, discuss it before reverting.

## Agent Tooling

### Accessing Library Documentation

Use the configured Context7 MCP server for up-to-date library docs instead of relying on
model memory:

- Call `resolve-library-id` with the library name, then call `query-docs` with the
  returned ID and a focused question describing the API or task you need help with.
- If multiple libraries match, prefer the closest name match with good reputation and
  coverage; ask the user when the intent is unclear.
- Keep responses concise and cite only the relevant snippets; avoid guessing when docs
  are available.

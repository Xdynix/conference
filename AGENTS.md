# Development Guidelines

Guidance for coding agents working in this repository. Directory-specific guides are
listed under [Directory Guides](#directory-guides); read every guide above the files
you edit.

## Project Overview

A Django application with an async-first architecture and ASGI deployment. The current
deployment target is SQLite; application code should remain database-backend agnostic.
The frontend uses Alpine.js with Bootstrap, served via Django templates (no SPA, no
bundlers).

## Development Setup

Required tools: **uv** (Python package management) and **just** (task runner).
`just dev-setup` performs first-time setup (dependencies, pre-commit hooks, dev
certificates); `just --list` shows the shortcuts humans use.

- **Targeted tests**: `uv run pytest <path>` (use `-q` or `-k` as needed). Coverage is
  not measured; add `-n auto` to parallelize larger runs.
- **Full suite**: `just test` enforces the 100% coverage gate. `just test <path>` fails
  on coverage, not on tests.
- **Django management**: `uv run manage.py <command>`.
- **Python with Django loaded**: `uv run manage.py shell -c "<code>"`. Never use
  `python -c` directly; Django apps require initialization.
- **Linters**: `just lint` (ruff, mypy, via pre-commit; also runs on commit).

## Project Structure

The project follows Django's app-based architecture.

### Django Apps

- **`app/core/`** - Core authentication and authorization (user, roles, sessions,
  password reset).
- **`app/conference/`** - The conference domain: papers, reviews and decisions,
  registrations, payments, proofs, tracks, user profiles, scoped roles, and invitations.
- **`app/verikit/`** - User identity verification toolkit (email verification).
- **`app/infra/`** - Infrastructure services (background jobs, scheduling, mutex locks).
- **`app/misc/`** - Health endpoint, favicon, and housekeeping jobs (e.g. session
  cleanup, mail retries, disk checks).
- **`app/admin/`** - Custom admin site (login, headers, permissions). Model-specific
  `ModelAdmin` registrations live in each app's own `admin.py` or `admin/` package.
- **`app/audit/`** - Structured audit logging. All mutation API endpoints must call
  `audit()` from this app to record who did what; `app/AGENTS.md` has the call pattern.
- **`app/frontend/`** - Frontend templates, static files, and views.

When adding new features, choose the app by responsibility:

- **Authentication/authorization** (users, sessions, global roles, passwords) -> `core`.
- **Conference domain logic** (papers, reviews, registrations, payments, profiles,
  invitations, tracks, scoped roles) -> `conference`.
- **Shared infrastructure touching Django** (jobs, scheduling, locks) -> `infra`.
- **Shared helpers that are not themselves a Django app** (no models of their own, no
  jobs) -> `utils`.
- **UI templates and frontend assets** -> `frontend`.

### Admin Surfaces

The word "admin" refers to two distinct surfaces; do not conflate them.

- **Django admin** - `app/admin/` plus each app's `ModelAdmin` registrations, served at
  `/admin/`. Gated to superusers only (`AdminSite.has_permission`), because fine-grained
  permissions are hard to secure and features like autocomplete can leak data. Use it
  for low-level model CRUD by maintainers, not for conference-scoped admin work.
- **Frontend admin UI** - user-facing conference management built as ordinary frontend
  pages under `app/frontend/templates/frontend/conference/admin/`, routed at
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

## Directory Guides

Every `AGENTS.md` above a file applies to it; the nearest wins on conflict.
`git ls-files '*AGENTS.md'` lists all of them. Current guides:

- **`app/AGENTS.md`** - Backend conventions for Python under `app/` (API endpoints,
  services, authorization, audit logging, background jobs).
- **`app/frontend/AGENTS.md`** - Templates, Alpine.js components, and static assets.
- **`tests/AGENTS.md`** - Test organization, fixtures, and API/service test patterns.
- **`docker/AGENTS.md`** - Deployment. Also covers `Dockerfile`, `docker-compose.yml`,
  and the production settings they reference; these files are coupled, so read the guide
  before editing any of them.
- **`WORKFLOWS.md`** (repository root) - State machines, transitions, actor roles, and
  step-by-step happy paths. Read it before implementing, modifying, or designing
  features that involve states, multistep user flows, or behavior spanning backend and
  frontend. New workflows follow its conventions and structure.

`CLAUDE.md` files are one-line includes so Claude Code loads the adjacent `AGENTS.md`
automatically; edit the `AGENTS.md`, not the include.

## Self-Review Protocol

After completing a non-trivial implementation, spawn a challenger subagent to review the
code before presenting it to the user. Skip this for trivial changes (one-liners,
renames, config tweaks) or when the design was already settled through interactive
discussion.

1. Implement the change.
2. Spawn a challenger subagent with the task description and the code written.
3. The challenger reviews within a single subagent session: on a **clear improvement**
   it revises and re-reviews (up to 2 cycles); on **comparable alternatives** with
   different trade-offs it stops and reports the options instead of choosing one.
4. Incorporate the findings, then present the result with a short review note (approach
   taken, concerns, alternatives considered). Omit the note when there is nothing
   meaningful to report.

Challenger principles:

- **Simplest correct solution.** Less code, fewer abstractions, or a more obvious
  approach wins. Never add complexity for hypothetical futures.
- **Fresh eyes.** Read the code as if someone else wrote it. Would the intent be clear
  to a new team member? Does the approach feel natural or forced?
- **Fit the codebase.** Check how similar problems are solved nearby; flag a new pattern
  where an existing one would work.
- **Clean code over formatting.** Linters handle spacing and import order. Focus on
  what they cannot catch: naming (do names communicate purpose?), organization (is
  logic in the right place?), and abstraction level (does a function mix high-level
  intent with low-level details?).
- **Challenge the "what", not just the "how".** Is the approach itself right? Is there a
  well-known pattern, or a different layer where this belongs?
- **Say nothing when there is nothing to say.** If the implementation is
  straightforward and sound, report that. Do not invent concerns to justify the review.

## Code Quality Standards

- **Linting and typing**: ruff (extensive rule set) and mypy strict mode with
  django-stubs, enforced by pre-commit. Rely on ruff format instead of manual reflowing
  beyond the 88-character target.
- **Testing**: pytest with a 100% coverage requirement on Python under `app/`.
- **Dependencies**: uv with dependency groups. Runtime deps go without a group; tooling
  goes to its group via `uv add --group dev|lint|test <package>`.
- **Migrations**: standard Django migrations with clear, focused intent. Humans may
  squash early-stage migrations.

## Writing and Code Style

- **Modern syntax only**: Target Python 3.14+ and the Django version pinned in
  `pyproject.toml`, with no concern for backward compatibility. Use built-in generics
  (`list[str]`, `dict[str, int]`), union syntax (`str | None`), and modern type hints.
  Never use `from __future__ import`, `typing.List`, `typing.Dict`, `typing.Optional`,
  or `Generic[]` base classes when built-in equivalents exist. Unparenthesized
  `except ErrorA, ErrorB:` is valid 3.14 syntax; do not "fix" it.
- Follow existing project conventions for formatting, naming, and architecture; new code
  should blend with surrounding modules.
- Keep natural-language output (e.g. logs, error messages, Markdown list items,
  comments) in complete sentences unless brevity is clearly preferred.
- Avoid em dashes entirely; use commas, semicolons, or parentheses instead.
- Do not wrap function parameters unnecessarily: keep them on one line within the
  88-character limit; otherwise, place each argument on its own line ending with a
  comma.
- Prefer `@classmethod` for shared helper methods. Reserve `@staticmethod` for
  documented special cases where binding to the class is undesirable (primarily Django
  Ninja resolver methods per upstream guidance).
- **Comments**: Write self-explanatory code. Do not add comments that repeat what the
  code does. Comment only design decisions, non-obvious behavior, or context that cannot
  be expressed through code.
- **Docstrings**: Google Style for Python functions and classes, except API view
  docstrings that serve the generated API documentation (keep those concise and
  reader-facing). Describe behavior from the caller's perspective, not implementation.
  Omit the `Args` section when all arguments are self-explanatory from their names and
  types.
- **Commits**: Subjects at or under 50 characters, body and footer lines at or under
  72 (commitlint enforces all three), conventional commit format with a type prefix and
  no scope (`fix: resolve session expiry`, not `fix(core): resolve session expiry`).

# Testing Guidelines

Conventions for the pytest suite under `tests/`.

## Layout

- Test packages mirror the app packages (`tests/<app>/api/`, `tests/<app>/services/`,
  and so on). Large test modules were split into packages with one module per operation
  (e.g. `tests/conference/services/paper/`). Add to that structure where it exists;
  split a module only when it grows unwieldy, not up front.
- `tests/conftest.py` holds the generic fixtures (e.g. API clients, global mocks, media
  root). `tests/base.py` holds shared test-case mixins; `tests/helpers.py` holds
  helpers such as `update_object()` (force a model into a state) and the `any_*` and
  `approx_now()` matchers; `tests/data.py` and `tests/data/` hold sample credentials
  and files.
- Doctests in `app/` modules run as part of the suite (`--doctest-modules`).

## Framework and Database Testing

- Use pytest with pytest-django, pytest-asyncio, and pytest-mock; the `test` dependency
  group in `pyproject.toml` lists the rest (e.g. faker, respx).
- Use `pytest-mock`'s `mocker` fixture instead of `unittest.mock.patch`.
- Use `@pytest.mark.django_db` for tests that access the database.
- Prefer synchronous tests whenever the system under test is synchronous; async test
  cases are only needed when the subject itself is async because sync tests are simpler
  and faster.
- If the system under test is async or the test covers transactional behavior (e.g.
  `IntegrityError` propagation, rollbacks, `transaction.on_commit`), mark the test
  function or suite with `@pytest.mark.django_db(transaction=True)`. A transaction
  inside the service is not by itself a reason.
- Use Django's async ORM methods (`acreate`, `acount`, `aexists`) in async tests.
- Do not add `@pytest.mark.asyncio`; pytest-asyncio handles async tests automatically.
- Annotate the `settings` fixture as `django.conf.LazySettings`, even though the fixture
  actually yields `pytest_django.Settings`. Only the former gives typed access to
  individual settings, including project-specific ones; the latter resolves every
  attribute to `Any`.

## Test Organization and Best Practices

- **Naming**: Use `test_happy_path` or `test_smoke` for main functionality tests and
  descriptive names for edge cases.
- **Structure**: Create helper factory functions with sensible defaults for test data
  setup.
- **Class-based vs Function-based Tests**: Both function-based and class-based tests are
  acceptable. Use class-based tests when there are several components in the same test
  file that need boundaries between them (e.g., to avoid sharing fixtures or helpers).
  Use function-based tests for simpler, standalone tests.
- **Fixtures**: Use fixtures for common mocks (e.g., `mock_send` fixture for email
  mocking). Promote a fixture to the nearest shared `conftest.py` once more than one
  module needs the same setup (root: API clients and global mocks; `tests/conference/`:
  domain objects and role holders). Subject fixtures that put a model into a
  test-specific state stay inline, even when the name repeats across modules.
- **Docstrings**: Do not add docstrings to test cases if their names are clear enough.
  Docstrings for test helpers are acceptable when they clarify complex setup or
  behavior.
- **Assertions**: Use `tests.helpers.any_*` values for flexible type-based assertions.
- **Code Quality**: Write concise assertions like
  `assert await Model.objects.filter().acount() == 1`.
- **Annotations**: Add `# noqa: ARG001` (functions) or `# noqa: ARG002` (methods) for
  intentionally unused fixture parameters.
- **Imports**: Import `MagicMock` from `unittest.mock` for better type hints.

## API Test Pattern

Cover these cases (see `tests/conference/api/conference/test_create.py` for examples):

- Happy path with full response and service call verification.
- Input parsing/sanitization and defaults.
- Validation errors with `loc`/`msg` assertions.
- Service exception -> HTTP response mapping.
- Authorization (unauthenticated, unauthorized, allowed roles).
- Partial updates: "omit keeps existing" and "empty clears value".

## Service Test Pattern

- Test services directly with `@pytest.mark.django_db`.
- Mock external dependencies (email, external APIs) but not the database.
- Test domain exceptions are raised for invalid states.
- See `tests/conference/services/` for examples.

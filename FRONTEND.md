# Frontend Architecture

This document defines the frontend implementation guidelines for the project.

## Technology Stack

| Layer         | Technology      |
|---------------|-----------------|
| CSS Framework | Bootstrap 5.3+  |
| Reactivity    | Alpine.js 3     |
| Icons         | Bootstrap Icons |
| HTTP Client   | axios           |

All frontend dependencies are downloaded locally and served via Django's static files
system. No npm, bundlers, or build steps are used. This avoids CDN connectivity issues.

### Optional Dependencies

| Library                 | Size          | Purpose                            |
|-------------------------|---------------|------------------------------------|
| SortableJS              | ~10KB         | Drag-and-drop reordering for lists |
| Tabulator / Grid.js     | ~50KB / ~12KB | Advanced data tables (if needed)   |
| Tom Select / Choices.js | ~20KB         | Autocomplete dropdowns (if needed) |

Add optional dependencies only when the use case justifies them. Start with Bootstrap +
Alpine.js for most needs.

### Browser Support

Target modern browsers only (latest Chrome, Firefox, Safari, Edge). No polyfills or
legacy compatibility. ES6+, CSS Grid, native `Intl` APIs are all safe to use.

Add meta tags to force modern engine in dual-engine browsers (QQ, 360, Sogou, etc.):

```html

<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<meta name="renderer" content="webkit">
```

Add a feature check early in the base template to show a clear message on old browsers
or when IE compatibility mode is triggered:

```html

<script>
  if (!window.fetch || !window.Intl || !window.Promise) {
    document.body.innerHTML =
      '<div style="padding:2rem;font-family:system-ui,sans-serif">' +
      '<h1>Browser Not Supported</h1>' +
      '<p>Please use a recent version of Chrome, Firefox, Safari, or Edge.</p></div>';
  }
</script>
```

## Core Principles

- **No SPA**: One Django view per route; no client-side routing.
- **API-First**: Frontend communicates with the backend primarily via RESTful API
  endpoints, not Django template-rendered dynamic data.
- **Django-Rendered Configuration**: Static configuration (CSRF token/header, reversed
  URLs, feature flags) is rendered by Django at page load into a global `window.APP`
  object.
- **Alpine.js Components**: Reusable UI behaviors are encapsulated as Alpine.js
  component functions.
- **Client-Side Data Processing**: Filtering, sorting, and searching are handled
  client-side. Data volumes are small (hundreds of items). For paginated endpoints,
  prefetch all pages or request a large page size.

## State Management

Use different storage mechanisms based on data characteristics:

| Data type             | Location     | Example                           |
|-----------------------|--------------|-----------------------------------|
| Static config         | `window.APP` | csrf, urls, params, feature flags |
| Reactive shared state | Alpine store | session, theme, notifications     |
| Component-local state | `x-data`     | form fields, loading state        |

**Alpine stores** provide Redux-like shared state without extra dependencies:

```javascript
// In api.js or a dedicated store file
Alpine.store("session", {
  user: null,
  conference: null,
  async load() {
    const response = await api.get(APP.urls.session);
    this.user = response.data.user;
    this.conference = response.data.conference;
  }
});

// Access in any component via $store
<span x-text="$store.session.user?.name"></span>
<button @click = "$store.session.load()" > Refresh < /button>
```

**Guidelines:**

- Initialize stores before Alpine starts (in `api.js` or via `Alpine.data()`).
- Keep stores focused (one per domain: session, theme, notifications).
- Use `window.APP` for data rendered by Django at page load.
- Use stores for data fetched client-side or shared across components.

## File Organization

All frontend code lives in the `frontend` app:

```text
app/frontend/
├── __init__.py
├── views.py                  # FrontendView and custom views
├── urls.py                   # All frontend routes
├── context_processors.py     # Global config
├── templates/
│   ├── base.html
│   ├── auth/                 # Login, signup, password reset
│   ├── conference/           # Conference selection, index
│   └── papers/               # Paper list, detail, edit
└── static/frontend/
    ├── vendor/               # Third-party libraries
    │   ├── bootstrap.min.css
    │   ├── bootstrap.bundle.min.js
    │   ├── bootstrap-icons.min.css
    │   ├── fonts/
    │   ├── alpine.min.js
    │   └── axios.min.js
    ├── js/
    │   ├── api.js            # API client, error mapping, form utilities
    │   ├── theme.js          # Dark mode handling
    │   └── components/       # Reusable Alpine components
    └── css/
        └── app.css           # Custom overrides (keep minimal)
```

Vendor files are committed to the repository. Update them manually when upgrading
library versions.

## Base Template Structure

The base template must:

1. Set `data-bs-theme="auto"` on `<html>` for dark mode support.
2. Load vendor files: Bootstrap CSS, Bootstrap Icons, Bootstrap JS, Alpine.js, axios.
3. Render a global `window.APP` object containing CSRF configuration and URL mappings.
4. Load `api.js` before page-specific scripts.

```html

<script>
  window.APP = {
    csrf: {token: "{{ csrf_token }}", header: "{{ csrf_header_name }}"},
    ctx: { /* page context, see below */},
    urls: { /* reversed URLs, see below */},
    config: { /* feature flags, Turnstile site key, etc. */}
  };
</script>
```

## URL Handling

Handle URL parameters based on when they're known:

| Context                    | Approach                                          |
|----------------------------|---------------------------------------------------|
| Single resource page       | Render full URL at page load                      |
| List page with row actions | Render base URL + JS function for dynamic segment |
| Fully dynamic (rare)       | Placeholder template + replace helper             |

**Example structure:**

```html

<script>
  window.APP = {
    ctx: {
      // Page context known at render time
      conference: "{{ conference.name }}"
    },
    urls: {
      // Static endpoints
      me: "{% url 'api:me' %}",

      // Context-bound endpoints (conference known)
      papers: "{% url 'api:paper-list' conference.name %}",

      // Dynamic endpoints as functions
      paper: (code) =>
        `{% url 'api:paper-list' conference.name %}${encodeURIComponent(code)}/`,
      paperAuthors: (code) =>
        `{% url 'api:paper-list' conference.name %}${encodeURIComponent(code)}/authors/`
    }
  };
</script>
```

For fully dynamic URLs with multiple parameters, use a placeholder pattern:

```javascript
APP.urls = {
  // ...
  paperReview: "{% url 'api:paper-review' conference.name '__PAPER__' '__REVIEW__' %}",

  // Helper function
  buildUrl: (template, params) => {
    let url = template;
    for (const [key, value] of Object.entries(params)) {
      url = url.replace(`__${key.toUpperCase()}__`, encodeURIComponent(value));
    }
    return url;
  }
}

// Usage
APP.buildUrl(APP.urls.paperReview, {paper: 'ABC', review: '123'})
```

## API Client

Configure a global axios instance with:

- Automatic CSRF header injection from `APP.csrf`.
- Request timeout (default 30 seconds).
- Response interceptor for structured error extraction (`{ status, message, errors }`).

For file uploads, axios provides upload progress via `onUploadProgress` callback.

```javascript
// Example: file upload with progress
await api.post('/upload', formData, {
  onUploadProgress: (e) => {
    progress = Math.round((e.loaded * 100) / e.total);
  }
});
```

### Response Data

Use plain objects for API responses; avoid wrapping in classes. Optionally, use JSDoc
for IDE autocompletion. For computed values needed across pages, use helper functions
rather than class methods.

## Error Handling

### Server Error Mapping

API error responses follow the structure `{ detail: string, errors: [{loc, msg}] }`.
A `mapErrors(errors)` utility converts the `loc` array to field names, enabling inline
error display per form field. Non-field errors map to a `_form` key.

### Client-Side Validation

Validate forms client-side before submission. Only submit if validation passes. Display
server-side errors when the request fails.

## Form Components

Use a factory pattern for form components:

- `data`: form field values.
- `errors`: mapped error messages per field.
- `loading`: submission state.
- `validate()`: client-side validation returning errors object.
- `submit()`: validates, calls API, maps errors on failure.
- `error(field)`: returns first error message for a field.
- `hasError(field)`: boolean check for field errors.

## Reusable Components

### Turnstile Integration

- Turnstile is required only on specific forms (login, registration, password reset).
- Use the visible widget style.
- Pass the Turnstile response token to the API client via the `turnstile` option.
- Turnstile site key is rendered in `APP.config.turnstileSiteKey`.

### Email Verification Flow

- In-memory state; losing state on page refresh is acceptable.
- Three steps: `input` (enter email) -> `verify` (enter code) -> `done` (verified).
- Produces a signed token stored in a hidden form field for subsequent submission.

### Data Tables

Build tables with Bootstrap + Alpine.js. Data volumes are small (hundreds of items), so
client-side processing is sufficient.

**Standard features (implement with Bootstrap + Alpine):**

- Client-side search, sort, and filter via computed properties
- Header/footer action buttons
- Row action dropdowns
- Expandable/collapsible rows (use `x-show` with `x-collapse`)
- Spanned rows (native `rowspan`/`colspan`)

**When to consider a table library (Tabulator, Grid.js):**

- Inline cell editing with validation
- Column drag-to-reorder or resize
- Virtual scrolling for 1000+ rows
- Complex features appearing across many tables

Start simple; extract common patterns into reusable components as they emerge. Only
introduce a library if complexity becomes painful.

### Nested Resources and Reordering

Forms with ordered nested items (e.g., paper authors) use an Alpine array with:

- Add/remove item buttons
- Move up/down buttons for reordering (always available for accessibility)
- Optional drag-and-drop via SortableJS (add when justified)
- Hidden input containing ordered IDs as JSON for form submission

Reorder endpoints expect a list of item IDs representing the new order. The component
maintains order in the Alpine array and serializes IDs on submit.

### Searchable Selection

For selecting items from a large set (users, papers, etc.), prefer a simple search +
select pattern over autocomplete dropdowns:

- Text input with debounced auto-search (`@input.debounce.400ms="search()"`)
- Results rendered as a list with context (name, email, affiliation)
- Each result has a "Select" button
- Fully accessible by default, works well on mobile

Alpine.js provides debounce as a built-in modifier; no external library (e.g., lodash)
is needed. Use `@keydown.enter.prevent="search()"` for explicit enter-to-search.

This pattern is simpler to implement (~30 lines Alpine) and provides better context per
result than cramped autocomplete dropdowns.

**When to consider autocomplete libraries:**

- Very frequent selection by power users
- Space-constrained UI where a dropdown is necessary
- Need for tagging or multi-select with type-ahead

**Autocomplete library options (if needed):**

| Library     | Size  | Notes                                     |
|-------------|-------|-------------------------------------------|
| Tom Select  | ~20KB | Selectize successor, tagging, remote data |
| Choices.js  | ~20KB | Clean API, good accessibility             |
| Slim Select | ~10KB | Lightweight, simpler feature set          |

### Dark Mode

- Stored in `localStorage` with values: `light`, `dark`, `auto`.
- `auto` follows system preference via `prefers-color-scheme`.
- Applied by setting `data-bs-theme` attribute on `<html>`.
- Toggle UI via Alpine.js store (`$store.theme`).

### Notifications

- Use Bootstrap toasts for transient feedback (success, error, info).
- Position toasts in a fixed container (top-right or bottom-right).

### Modals

- Use Bootstrap modal component when inline forms or confirmation dialogs are needed.
- Keep modal content simple; prefer full-page flows for complex forms.

### Loading States

- Use Bootstrap spinner for loading indicators.
- Disable submit buttons during requests to prevent double-submission.
- Show loading state while fetching data; hide content until ready.

```html

<button type="submit" :disabled="loading">
  <span x-show="loading" class="spinner-border spinner-border-sm"></span>
  Submit
</button>
```

### Date and Time

Server returns timezone-aware ISO format strings. Format for display using native
`Intl.DateTimeFormat` (no library needed):

```javascript
// User's local timezone
new Date(isoString).toLocaleString()

// With formatting options
new Intl.DateTimeFormat('en-US', {dateStyle: 'medium', timeStyle: 'short'})
  .format(new Date(isoString))
```

### Navigation

Use Bootstrap sidebar with collapsible multi-level menu for dashboard navigation.
Collapse component handles expand/collapse behavior.

### Footer

Reserve space for common footer links (privacy policy, terms, contact). Content is
not an engineering concern, but leave room in the layout so links can be added when
requested without redesigning.

## Django Views

Views render template shells; frontend fetches data via API. This avoids duplicating
logic between views and API endpoints.

**Generic frontend view:**

```python
# app/frontend/views.py
class FrontendView(LoginRequiredMixin, TemplateView):
    """Renders template with URL params. Frontend fetches data via API."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['params'] = self.kwargs
        return context


# app/frontend/urls.py
urlpatterns = [
    path('papers/', FrontendView.as_view(template_name='papers/list.html')),
    path('papers/<str:code>/',
         FrontendView.as_view(template_name='papers/detail.html')),
]
```

Use generic view for simple pages. Create specific view classes only when custom logic
is needed (different auth, extra context).

**Global config via context processor:**

```python
# app/frontend/context_processors.py
def frontend_config(request):
    return {
        'csrf_header_name': settings.CSRF_HEADER_NAME,
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
    }
```

## Code Organization

Place JavaScript logic based on reusability:

<!-- markdownlint-disable MD013 -->

| Logic type            | Location                            | Rationale                  |
|-----------------------|-------------------------------------|----------------------------|
| Page-specific         | Inline `<script>` block in template | Co-located, self-contained |
| Reusable across pages | `static/js/components/*.js`         | Shared, lintable           |
| Core utilities        | `static/js/api.js`                  | API client, error mapping  |

<!-- markdownlint-enable MD013 -->

**Page-specific logic** stays in the template, similar to single-file components:

```html
{% block content %}
<div x-data="pageData()">
  <!-- page markup -->
</div>
{% endblock %}

{% block scripts %}
<script>
  function pageData() {
    return {
      items: [],
      async init() {
        this.items = await api.get('{{ items_url }}');
      }
    };
  }
</script>
{% endblock %}
```

**Reusable components** (email verification, data tables) go in `static/js/components/`
and are loaded globally or per-page as needed.

## Developer Tooling

**Browser extensions:**

- Alpine.js Devtools: Inspect component data, watchers, and events live.

**IDE type support:**

Install TypeScript definitions for vendor libraries to enable autocompletion:

```bash
npm install --save-dev @types/bootstrap axios alpine-types
```

These are dev-only dependencies for IDE support; they do not affect runtime.

**Linting (via pre-commit):**

- Biome: Lint and format `.js` files in `static/js/`.
- djLint: Lint Django template structure and HTML.

Inline `<script>` blocks in templates are not linted; keep page-specific logic simple.
Complex logic should be extracted to lintable `.js` files.

## Coding Guidelines

- Keep custom CSS minimal; leverage Bootstrap utilities and components.
- Page-specific Alpine logic stays inline in templates; reusable components go in
  `static/js/components/`.
- Use `x-cloak` to hide Alpine-controlled elements until initialization.
- Always use `:key` with `x-for` loops for correct reactivity during reordering.
- Prefer semantic HTML and Bootstrap's accessibility features.

## Help Patterns

Preliminary thoughts on contextual help; may evolve during implementation.

**Hybrid approach:**

- Field-level hints: tooltips or popovers (quick, inline)
- Page-level help: offcanvas side panel (detailed, stays open while working)

| Pattern     | Use case                   | Component                    |
|-------------|----------------------------|------------------------------|
| Tooltip     | Brief hint (1 line)        | Bootstrap tooltip            |
| Popover     | Multi-line explanation     | Bootstrap popover            |
| Inline text | Always-visible guidance    | `<small class="text-muted">` |
| Side panel  | Page-level help, workflows | Bootstrap offcanvas          |

**Guidelines:**

- Standard help icon: `bi-question-circle` placed consistently (e.g., next to labels).
- Page-level help button in header opens offcanvas panel.
- Side panel content can include accordion for multiple topics.
- Keep help content in templates, co-located with the page.
- For touch devices, use `data-bs-trigger="focus"` instead of hover.
- Include `<span class="visually-hidden">` for accessibility.

## Security

**Content Security Policy (CSP):**

Currently using relaxed CSP (`'unsafe-inline'` for scripts) to support inline `<script>`
blocks and Alpine.js directives. This is acceptable for internal dashboard use.

When Django 6.0 is available, migrate to strict CSP using Django's built-in CSP
utilities with nonce-based script allowlisting.

**XSS Prevention:**

- Use `x-text` for displaying data (escapes HTML, safe).
- Avoid `x-html` unless content is sanitized server-side.
- Validate URLs before binding to `href` (block `javascript:` protocol).

```html
<!-- Safe -->
<span x-text="user.name"></span>

<!-- Dangerous - only use with trusted/sanitized content -->
<div x-html="trustedHtml"></div>

<!-- URL binding - validate protocol -->
<a :href="url.startsWith('http') ? url : '#'">Link</a>
```

## Testing

**Strategy:**

| Concern             | Approach                   |
|---------------------|----------------------------|
| Business logic      | Python API tests (backend) |
| Critical user flows | Playwright E2E tests in CI |
| UI wiring, layout   | Manual during development  |

**E2E testing with Playwright:**

Use `pytest-playwright` to keep tests in Python alongside backend tests. Add E2E tests
for critical flows (login, paper submission, review workflow) once UI stabilizes.

JS unit tests (Vitest, Jest) require Node.js tooling, which conflicts with the no-npm
approach. Backend API tests cover business logic; E2E tests catch UI wiring issues.

## Accessibility

Baseline approach: don't break what Bootstrap and semantic HTML provide for free.

**Always do (low effort):**

- Use semantic elements (`<button>`, `<a>`, `<input>`, not `<div>` with click handlers)
- Associate labels with form inputs (`<label for="">`)
- Add `visually-hidden` text to icon-only buttons
- Keep Bootstrap's focus outlines (don't remove `:focus` styles)
- Use logical heading order (`h1` → `h2` → `h3`)
- Add alt text to meaningful images

**Bootstrap handles:**

- Modal focus trapping and restoration
- Color contrast in default theme
- ARIA attributes on components (dropdowns, tabs, etc.)

Full WCAG compliance is not a current priority. Address specific accessibility requests
from users as they arise.

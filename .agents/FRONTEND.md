# Frontend Guidelines

This document defines frontend implementation patterns for the project.

## Technology Stack

| Layer             | Technology      |
|-------------------|-----------------|
| CSS Framework     | Bootstrap 5.3+  |
| Reactivity        | Alpine.js 3     |
| Icons             | Bootstrap Icons |
| HTTP Client       | axios           |
| Searchable Select | Tom Select      |

All frontend dependencies are downloaded locally and served via Django's static files
system. No npm, bundlers, or build steps are used.

Vendor files are committed to the repository. Update them manually when upgrading
library versions.

### Browser Support

Target modern browsers only (latest Chrome, Firefox, Safari, Edge). No polyfills or
legacy compatibility. ES6+, CSS Grid, native `Intl` APIs are all safe to use.

## Core Principles

- **No SPA**: One Django view per route; no client-side routing.
- **API-First**: Frontend fetches data via API, not Django template-rendered dynamic
  data.
- **Django-Rendered Configuration**: Static config (CSRF, URLs, feature flags) rendered
  into `window.APP` at page load.
- **Alpine.js Components**: Reusable UI behaviors encapsulated as component functions.
- **Single-File Pattern**: Inspired by Vue's Single-File Components, each page/component
  keeps its HTML and JavaScript together in one file for easier maintenance.

## Layouts

Two layout types, both include the navbar.

### Simple Layout

Centered content without sidebar. Used for authentication pages and account settings.

-> Example: `app/frontend/templates/frontend/layouts/simple.html`

Pages using this layout:

- Login, registration, password reset
- Account settings
- Conference selection

### App Layout

Navbar with sidebar for conference-scoped pages. Sidebar provides role-based navigation.

Pages using this layout must set the active sidebar item and breadcrumb via stores:

```html

<div x-data x-init="
  $store.sidebar.setActive('home');
  $store.breadcrumb.set([{label: 'Home'}]);
"></div>
```

**Breadcrumb rules:**

- Each top-level sidebar item is its own breadcrumb root (no `Home >` prefix on every
  page).
- Last item (current page) has no `url` property.
- Ancestor items include `url` for navigation.

```javascript
// Top-level page
$store.breadcrumb.set([{label: 'My Papers'}]);

// Nested page (prefer {% url %} for static URLs)
$store.breadcrumb.set([
  {
    label: 'My Papers',
    url: '{% url "frontend:paper-list" conference_name=params.conference_name %}'
  },
  {label: 'PAPER-2000'}
]);

// Deep page
$store.breadcrumb.set([
  {
    label: 'My Papers',
    url: '{% url "frontend:paper-list" conference_name=params.conference_name %}'
  },
  {
    label: 'PAPER-2000',
    url: APP.urls.pages.paperDetail(APP.params.conference_name, 'PAPER-2000')
  },
  {label: 'Reviews'}
]);
```

-> Example: `app/frontend/templates/frontend/layouts/app.html`,
`app/frontend/templates/frontend/conference/home.html`

## Views

Two view classes handle authentication requirements:

```python
# Public pages (login, registration)
path("login/", public_view(template_name="frontend/login.html"))

# Protected pages (require authentication)
path("account/", protected_view(template_name="frontend/account.html"))
```

-> Example: `app/frontend/views.py`, `app/frontend/urls.py`

## State Management

| Data Type             | Location     | Example                        |
|-----------------------|--------------|--------------------------------|
| Static config         | `APP.config` | CSRF, upload limits, site name |
| Enum definitions      | `APP.enums`  | PaperState, ConferenceRole     |
| Page parameters       | `APP.params` | conference_name, paper_code    |
| API URLs              | `APP.urls`   | session.get, myPaper.create    |
| Reactive shared state | Alpine store | Session, theme, conference     |
| Component-local state | `x-data`     | Form fields, loading, errors   |

-> Example: `app/frontend/static/frontend/js/stores.js`

### URL State Management

For pages with filters, pagination, or other URL-persisted state, use the `UrlState`
utility (`app/frontend/static/frontend/js/url-state.js`).

**Define a schema** with typed fields:

```javascript
const {string, number, boolean, oneOf, setOf} = UrlState.types;

const schema = {
  search: string({default: ''}),
  page: number({default: 1, min: 1}),
  sort: oneOf(['name', 'date'], {default: 'name'}),
  status: setOf(oneOf(['draft', 'submitted'], {default: ''}), {
    default: ['draft'],
  }),
};
```

**Integrate with Alpine.js** using the `use()` mixin:

```javascript
function myComponent() {
  return {
    ...UrlState.use(schema),

    init() {
      this.initUrlState();  // Required: call in init()
    },

    // Access via this.urlState.search, this.urlState.page, etc.
  };
}
```

**Key points:**

- State syncs bidirectionally with URL query parameters.
- Default values are omitted from URL for cleaner links.
- Uses `replaceState` (not `pushState`) to avoid polluting browser history.
- Type helpers validate and clamp values on load.

## API Client

The API client (`app/frontend/static/frontend/js/api.js`) is a configured axios instance
with automatic CSRF handling and mutation tracking.

**Mutation tracking**: Non-GET requests increment a pending counter. If the user tries
to leave the page with pending mutations, a `beforeunload` warning is shown. This
prevents accidental data loss during saves.

**Usage**:

```javascript
// CSRF header is automatically included
const {data} = await api.post(APP.urls.paper.create, payload);
const {data} = await api.patch(APP.urls.paper.update(code), payload);
const {data} = await api.delete(APP.urls.paper.delete(code));
```

## Forms

### Pattern

Forms use a factory function pattern with standard properties:

```javascript
function profileForm() {
  return {
    form: {givenName: "", familyName: ""},
    errors: {},
    loading: false,
    success: false,

    init() {
      // Initialize from store or API
    },

    async submit() {
      if (this.loading) return;  // Prevent double submit
      this.errors = {};
      this.loading = true;

      try {
        const {data} = await api.patch(APP.urls.endpoint, this.form);
        this.success = true;
      } catch (error) {
        const data = error.response?.data;
        if (error.response?.status === 422 && data?.details?.length) {
          this.errors = mapErrors(data.details);
        } else {
          this.errors._form = data?.message || "An unexpected error occurred.";
        }
      } finally {
        this.loading = false;
      }
    },
  };
}
```

-> Example: `app/frontend/templates/frontend/account.html`,
`app/frontend/templates/frontend/login.html`

### Key Points

- **Double-submit guard**: Always check `if (this.loading) return;` at start of submit.
- **Error mapping**: Use `mapErrors()` to convert API errors to field-keyed object.
- **Form-level errors**: Non-field errors go to `errors._form`.
- **Loading state**: Disable submit button with `:disabled="loading"`.
- **Full-width button**: Wrap in `<div class="d-grid">` for full-width submit button.
- **Store data freshness**: When populating from a cached store, watch for updates to
  avoid stale data. Use `$watch("$store.session.user", () => this.populateFromStore())`.

### Error Display

```html
<input
  :class="{ 'is-invalid': errors.given_name }"
  x-model="form.givenName"
>
<div class="invalid-feedback" x-text="errors.given_name"></div>
```

### Naming Conventions

<!-- markdownlint-disable MD013 -->

| Context         | Convention | Example                                                     |
|-----------------|------------|-------------------------------------------------------------|
| HTML `id`/`for` | kebab-case | `given-name`, `region-code`                                 |
| Form fields     | camelCase  | `form.givenName`, `form.regionCode`                         |
| Error keys      | snake_case | `errors.given_name`, `errors.region_code`                   |
| `autocomplete`  | standard   | `given-name`, `family-name`, `organization`, `country-name` |

Form fields use camelCase because they are local JavaScript state. Error keys use
snake_case because they come directly from API validation responses (the `loc` field in
error details). This separation makes it clear which values are internal state versus
API contract.

Autocomplete tokens follow the
[HTML standard](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#autofill-field).

<!-- markdownlint-enable MD013 -->

## Reusable Components

### Template Include Pattern

Components are Django template includes with parameters:

<!-- markdownlint-disable MD013 -->

```html
{% include "frontend/components/region-select.html" with id="region-code" label="Region" model="form.regionCode" error_key="region_code" required=True autocomplete="country-name" %}
```

<!-- markdownlint-enable MD013 -->

The `model` parameter uses camelCase (path to form field), while `error_key` uses
snake_case (matches API error `loc`).

Document parameters in a comment block at the top of the component file.

-> Example: `app/frontend/templates/frontend/components/password-input.html`

### Component Data via Template Tags

When a component needs static data, use a template tag to render JSON into a script tag:

```python
# templatetags/frontend_tags.py
@register.simple_tag
def regions_json() -> SafeString:
    regions = [[r.name, r.value] for r in Region]
    return mark_safe(json.dumps(regions))
```

```html
<!-- In base.html -->
<script type="application/json" id="app-regions">{% regions_json %}</script>

<!-- In component -->
const regions = JSON.parse(document.getElementById('app-regions').textContent);
```

-> Example: `app/frontend/templatetags/frontend_tags.py`

### Searchable Dropdown (Tom Select)

Use Tom Select for searchable dropdowns with large option lists (e.g., regions).
Initialize inline with Alpine's `x-init`:

```html
<select
  id="region-code"
  class="form-select"
  x-init="
    const regions = JSON.parse(document.getElementById('app-regions').textContent);
    $el._ts = new TomSelect($el, {
      options: regions.map(r => ({value: r[0], text: r[1]})),
      maxOptions: null,
      onChange: (v) => { form.regionCode = v; }
    });
    if (form.regionCode) $el._ts.setValue(form.regionCode, true);
    $watch('form.regionCode', (v) => {
      if ($el._ts.getValue() !== (v || '')) $el._ts.setValue(v || '', true);
    });
  "
  x-effect="$el._ts?.wrapper.classList.toggle('is-invalid', !!errors.region_code)"
  required
>
  <option value="">Select region...</option>
</select>
<div
  class="invalid-feedback"
  :class="{ 'd-block': errors.region_code }"
  x-text="errors.region_code"
></div>
```

**Key points:**

- `class="form-select"` prevents style flash before Tom Select initializes
- `maxOptions: null` shows all options (default limits to 50)
- `$watch` syncs external model changes to Tom Select
- `x-effect` toggles `is-invalid` on the wrapper for Bootstrap validation styling
- Error feedback needs `d-block` class since Tom Select breaks Bootstrap's sibling
  selector

-> Example: `app/frontend/templates/frontend/account.html`

## URL Configuration

Prefer `{% url %}` in templates when the URL can be built server-side. Use
`window.APP.urls` only for dynamic cases that need runtime parameters or when building
URLs from data not available to the template.

URLs are rendered into `window.APP.urls` by Django, grouped by resource:

```javascript
window.APP = {
  config: {
    csrf: {cookie: "{% csrf_cookie_name %}", header: "{% csrf_header_name %}"},
    siteName: "...",
    upload: {submission: {maxSize: 20971520, allowedTypes: [...]}, ...},
  },
  enums: {PaperState: {...}, ...},
  params: {conference_name: "icse-2025", ...},
  urls: {
    session: {
      get: "{% url 'api-1.0.0:get-session' %}",
      delete: "{% url 'api-1.0.0:delete-session' %}",
    },
    conference: {get: urlTemplate(...)},
    paper: {get: urlTemplate(...)},
    // ... more resource groups
    pages: {
      conferenceHome: urlTemplate(...),
      paperDetail: urlTemplate(...),
      adminPaperDetail: urlTemplate(...),
      // ... more page URL builders
    },
  },
};
```

### Dynamic URL Segments

Use `urlTemplate()` for URLs with dynamic segments:

<!-- markdownlint-disable MD013 -->

```javascript
// In base.html - define with placeholders
urls: {
  paper: {
    get: urlTemplate(
      "{% url 'api-1.0.0:get-my-paper' '__CONFERENCE_NAME__' '__PAPER_CODE__' %}",
      "conference_name", "paper_code"
    )
  }
}

<!-- markdownlint-enable MD013 -->

// Usage - call with values
APP.urls.paper.get("icse-2025", "PAPER-2000")
```

**Placeholder types:**

- Named: `__PARAM_NAME__` for string params (e.g., `"conference_name"` ->
  `__CONFERENCE_NAME__`)
- ULID: Sequential placeholder ULIDs for ULID params (use `"ulid"` as param name)

-> Example: `app/frontend/templates/frontend/layouts/base.html`

## Context Processor

Injects Cloudflare Turnstile configuration into all template contexts:

```python
def cf_turnstile(_: Any) -> dict[str, Any]:
    return {
        "cf_turnstile": {
            "enabled": enabled,
            "site_key": settings.CF_TURNSTILE_SITE_KEY,
            "response_header_name": settings.CF_TURNSTILE_RESPONSE_HEADER_NAME,
        },
    }
```

Other global values (`site_name`, `csrf_cookie_name`, `redirect_field_name`, etc.) are
provided by template tags in `app/frontend/templatetags/frontend_tags.py`, not context
processors.

-> Implementation: `app/frontend/context_processors.py`

## Enums

Python enums are exported to `window.APP.enums` with `value` and `label` for each
member. To add a new enum, add it to `enums_json()` in
`app/frontend/templatetags/frontend_tags.py`. Enums with collection methods (e.g.,
`ConferenceRole.admins()`) can export them via the `collections` parameter.

```javascript
// Compare against API response
if (data.state === APP.enums.InvitationState.ACCEPTED.value) { ...
}

// Display label (lookup by value)
<span x-text="enumLabel(APP.enums.InvitationState, item.state)"></span>

// Check membership in a collection
APP.enums.ConferenceRole._collections.admins.includes(user.role)
```

-> Implementation: `app/frontend/templatetags/frontend_tags.py` (`_enum_to_dict`,
`enums_json`), `app/frontend/static/frontend/js/utils.js` (`enumLabel`)

### Role-Based Permissions

The `permissions` Alpine store (computed from the user's session and conference profile)
provides boolean flags for UI gating:

| Flag                | Meaning                                       |
|---------------------|-----------------------------------------------|
| `isChairRole`       | Superuser, global admin, or conference chair. |
| `isConferenceAdmin` | Above, plus conference secretary.             |
| `hasAdminRole`      | Above, plus track chair or secretary.         |
| `canReview`         | Above, plus conference or track reviewer.     |

Use these in templates to control visibility of admin pages, review sections, and other
role-gated UI:

```html

<template x-if="$store.permissions.hasAdminRole">
  <a href="...">Admin Settings</a>
</template>
```

For finer-grained checks (e.g., specific track roles or role assignment UI), access the
profile directly:

```javascript
const roles = $store.conference.profile?.conference_roles;
const trackRoles = $store.conference.profile?.track_roles;
```

-> Implementation: `app/frontend/static/frontend/js/stores.js` (permissions effect).

## Utilities Reference

Common utilities in `app/frontend/static/frontend/js/utils.js`:

| Function              | Purpose                                            |
|-----------------------|----------------------------------------------------|
| `mapErrors(details)`  | Convert API validation errors to field-keyed map   |
| `enumLabel(enum, v)`  | Look up enum label by value                        |
| `formatDate(iso)`     | Format ISO date string                             |
| `formatDateRange()`   | Format date range with smart month/year handling   |
| `formatFileSize()`    | Human-readable file size (KB, MB, etc.)            |
| `validateFile()`      | Validate file against upload constraints           |
| `formatProfileName()` | Format name from given_name/family_name fields     |
| `paperStateBadge()`   | Get badge class and label for paper state          |
| `reviewStateBadge()`  | Get badge class and label for review state         |
| `regionName(code)`    | Look up region name by code                        |
| `safeRedirectUrl()`   | Validate redirect URL is same-origin               |
| `urlTemplate()`       | Create URL builder from template with placeholders |

## Dark Mode

- Stored in `localStorage` with values: `light`, `dark`, `auto`.
- `auto` follows system preference via `prefers-color-scheme`.
- Applied by setting `data-bs-theme` attribute on `<html>`.
- Toggle in navbar with dropdown (Light, Dark, Auto options).

-> Example: `app/frontend/templates/frontend/components/navbar.html`

## Loading States

```html

<button type="submit" :disabled="loading">
  <span
    x-show="loading"
    x-cloak
    class="spinner-border spinner-border-sm me-1"
  ></span>
  Save
</button>
```

## Date and Time

Format ISO strings using native `Intl.DateTimeFormat`:

```javascript
new Intl.DateTimeFormat('en-US', {dateStyle: 'medium', timeStyle: 'short'})
  .format(new Date(isoString))
```

## Security

### XSS Prevention

- Use `x-text` for displaying data (escapes HTML).
- Avoid `x-html` unless content is sanitized server-side.
- Validate URLs before binding to `href`.

```html
<!-- Safe -->
<span x-text="user.name"></span>

<!-- URL binding - validate protocol -->
<a :href="url.startsWith('http') ? url : '#'">Link</a>
```

### Content Security Policy

Currently using relaxed CSP (`'unsafe-inline'`) for inline scripts and Alpine.js
directives. When Django 6.0 is available, migrate to nonce-based script allowlisting.

## Accessibility

Baseline approach: don't break what Bootstrap and semantic HTML provide for free.

**Always do:**

- Use semantic elements (`<button>`, `<a>`, `<input>`)
- Associate labels with inputs (`<label for="">`)
- Add `visually-hidden` text to icon-only buttons
- Keep Bootstrap's focus outlines
- Use logical heading order

## Code Organization

| Templates           | Location                         |
|---------------------|----------------------------------|
| Layouts             | `templates/frontend/layouts/`    |
| Reusable components | `templates/frontend/components/` |
| Conference pages    | `templates/frontend/conference/` |
| Public pages        | `templates/frontend/*.html`      |

| JavaScript     | Location                          |
|----------------|-----------------------------------|
| Core utilities | `static/frontend/js/utils.js`     |
| API client     | `static/frontend/js/api.js`       |
| Alpine stores  | `static/frontend/js/stores.js`    |
| URL state      | `static/frontend/js/url-state.js` |

Page-specific logic goes in inline `<script>` tags. Inline scripts are not linted;
extract complex logic to `.js` files for linting.

## Coding Conventions

- Keep custom CSS minimal; use Bootstrap utilities.
- Use `x-cloak` to hide Alpine-controlled elements until initialization.
- Use `:key` with `x-for` loops for correct reactivity.
- Prefer `@mousedown.prevent` over `@click` when blur timing matters.
- Prefer literal UTF-8 characters over HTML entity escapes (e.g., use `·` instead of
  `&middot;`). Only escape characters with special HTML meaning (`&lt;`, `&gt;`,
  `&amp;`, `&quot;`).
- Never use `x-show` on the same element as `d-flex` or other Bootstrap display
  utilities (`d-block`, `d-grid`, etc.). Bootstrap uses `!important` which overrides
  Alpine's inline `display: none`. Use `x-if` with `<template>` instead, or put `x-show`
  on a parent/wrapper.

## Text Styling

Use Bootstrap utility classes to create a clear visual hierarchy across different text
roles. The key principle: text importance should match visual weight.

<!-- markdownlint-disable MD013 -->

| Text Role                | Style                     | Classes                                                            | Example                         |
|--------------------------|---------------------------|--------------------------------------------------------------------|---------------------------------|
| Form labels              | Normal weight, body color | `form-label` (no `text-muted`)                                     | "Title", "Email"                |
| Form hints               | Muted, italic, small      | `form-text text-muted fst-italic` or `text-muted small fst-italic` | "150 characters or fewer."      |
| Empty states             | Normal body text          | No `text-muted`, no italic                                         | "No authors added yet."         |
| Error/terminal states    | Normal body text          | No `text-muted`                                                    | "Conference not found."         |
| Loading states           | Muted                     | `text-muted`                                                       | "Loading..."                    |
| Data display (secondary) | Muted, small              | `text-muted small`                                                 | Author affiliation in view mode |

<!-- markdownlint-enable MD013 -->

**Form labels** use plain `form-label` without `text-muted`. Labels guide the user to
inputs and need full visual weight.

**Form hints** use `fst-italic` in addition to `text-muted` and size classes. The italic
creates a typographic distinction from labels that works equally well in light and dark
themes, since it changes shape rather than relying on subtle color differences.

**Empty states** ("No items yet", "No reviews assigned") use normal body text. These are
informational content, not decoration; the wording itself communicates absence. Muting
them hides the signal.

**Error and terminal states** ("Not found", "Failed to load") use normal body text.
These are dead ends the user must notice.

## Table-Like List Layout

Use CSS Grid for tabular data lists (e.g., members, tracks, code pools). The pattern
uses a CSS custom property for column definitions so that headers and rows stay aligned.

### Structure

Wrap the table content (header + rows) in a scrollable container that defines the column
variable:

<!-- markdownlint-disable MD013 -->

```html

<div style="overflow-x: auto; --cols: minmax(10rem,1fr) 14rem 12rem 4rem;">
  {# Header #}
  <div
    class="d-grid align-items-center px-3 py-2 border-bottom bg-body-tertiary small text-muted"
    style="grid-template-columns: var(--cols); column-gap: 0.5rem;"
  >
    <span>Name</span>
    <span>Email</span>
    ...
  </div>

  {# Rows #}
  <template x-for="item in items" :key="item.uid">
    <div class="border-top">
      <div
        class="d-grid align-items-center px-3 py-2"
        style="grid-template-columns: var(--cols); column-gap: 0.5rem;"
      >
        <span class="fw-medium text-truncate" x-text="item.name"></span>
        ...
      </div>
    </div>
  </template>
</div>
```

<!-- markdownlint-enable MD013 -->

### Key Rules

- **Use `minmax(Xrem, 1fr)` for the flexible column**, not `minmax(0, 1fr)`. A zero
  minimum allows the column to collapse to nothing, which means `overflow-x: auto` never
  triggers (the grid just squishes instead of overflowing). A reasonable minimum (e.g.,
  `10rem`) ensures horizontal scroll kicks in when the container is too narrow.
- **Role-conditional columns**: When columns differ by role, use Alpine's `:style` to
  set
  the custom property dynamically:

<!-- markdownlint-disable MD013 -->

  ```html

<div
  style="overflow-x: auto;"
  :style="{'--cols': isAdmin ? 'minmax(10rem,1fr) 8rem 10rem' : 'minmax(10rem,1fr) 8rem'}"
>
  ```

<!-- markdownlint-enable MD013 -->

-> Example: `app/frontend/templates/frontend/conference/admin/members.html`,
`app/frontend/templates/frontend/conference/admin/settings.html`

## Testing

Frontend testing is not yet implemented. When added, tests will use pytest with
Playwright for end-to-end browser testing.

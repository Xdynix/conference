# Frontend Guidelines

This document defines frontend implementation patterns for the project. Examples
reference actual files in the codebase.

## Technology Stack

| Layer         | Technology      |
|---------------|-----------------|
| CSS Framework | Bootstrap 5.3+  |
| Reactivity    | Alpine.js 3     |
| Icons         | Bootstrap Icons |
| HTTP Client   | axios           |

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

## Layouts

Two layout types, both include the navbar.

### Simple Layout

Centered content without sidebar. Used for authentication pages and account settings.

→ Example: `app/frontend/templates/frontend/layouts/simple.html`

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

// Nested page
$store.breadcrumb.set([
  {label: 'My Papers', url: APP.urls.pages.myPapers(APP.params.conference_name)},
  {label: 'PAPER-2000'}
]);

// Deep page
$store.breadcrumb.set([
  {label: 'My Papers', url: APP.urls.pages.myPapers(APP.params.conference_name)},
  {
    label: 'PAPER-2000',
    url: APP.urls.pages.paper(APP.params.conference_name, 'PAPER-2000')
  },
  {label: 'Reviews'}
]);
```

→ Example: `app/frontend/templates/frontend/layouts/app.html`,
`app/frontend/templates/frontend/conference/home.html`

## Views

Two view classes handle authentication requirements:

```python
# Public pages (login, registration)
path("login/", public_view(template_name="frontend/login.html"))

# Protected pages (require authentication)
path("account/", protected_view(template_name="frontend/account.html"))
```

→ Example: `app/frontend/views.py`, `app/frontend/urls.py`

## State Management

| Data Type             | Location     | Example                      |
|-----------------------|--------------|------------------------------|
| Static config         | `window.APP` | CSRF, URLs, feature flags    |
| Reactive shared state | Alpine store | Session, theme               |
| Component-local state | `x-data`     | Form fields, loading, errors |

→ Example: `app/frontend/static/frontend/js/stores.js`

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

→ Example: `app/frontend/templates/frontend/account.html`,
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

The `model` parameter uses camelCase (path to form field), while `error_key` uses
snake_case (matches API error `loc`).

<!-- markdownlint-enable MD013 -->

Document parameters in a comment block at the top of the component file.

→ Example: `app/frontend/templates/frontend/components/password-input.html`

### Component Data via Template Tags

When a component needs data that shouldn't be in the global context processor, use a
template tag:

```python
# templatetags/frontend_tags.py
@register.simple_tag
def regions_json() -> str:
    return json.dumps([[r.name, r.value] for r in Region])
```

```html
<!-- In component -->
{% load frontend_tags %}
<div x-data="regionSelect({% regions_json %})">
```

→ Example: `app/frontend/templatetags/frontend_tags.py`

### Searchable Dropdown

For selecting from a large static list (e.g., regions):

- Text input that filters options as user types
- Dropdown list with filtered results
- Keyboard navigation: arrows to move, Enter to select, Escape to close
- `@blur` closes dropdown; `@mousedown.prevent` on options ensures selection before blur
- Hidden input holds the selected value for form submission
- Optional `autocomplete` attribute (default: `off`)

→ Example: `app/frontend/templates/frontend/components/region-select.html`

### Password Input

Password field with show/hide toggle:

- Toggle button with eye icon
- Configurable autocomplete (`current-password`, `new-password`)

→ Example: `app/frontend/templates/frontend/components/password-input.html`

## URL Configuration

URLs are rendered into `window.APP.urls` by Django, grouped by resource:

```javascript
window.APP = {
  urls: {
    session: {
      get: "{% url 'api-1.0.0:get-session' %}",
      create: "{% url 'api-1.0.0:create-session' %}",
    },
    user: {
      updateProfile: "{% url 'api-1.0.0:update-current-user-profile' %}",
    },
  },
};
```

For dynamic URL segments, use functions:

```javascript
urls: {
  // Dynamic segment appended to base URL
  paper: (code) =>
    `{% url 'api:papers' conference.name %}${encodeURIComponent(code)}/`,

    // Multiple dynamic segments via placeholder replacement
    paperReview
:
  "{% url 'api:paper-review' conference.name '__PAPER__' '__REVIEW__' %}",

    buildUrl
:
  (template, params) => {
    let url = template;
    for (const [key, value] of Object.entries(params)) {
      url = url.replace(`__${key.toUpperCase()}__`, encodeURIComponent(value));
    }
    return url;
  },
}

// Usage
APP.urls.paper('ABC-123')
APP.buildUrl(APP.urls.paperReview, {paper: 'ABC', review: '123'})
```

→ Example: `app/frontend/templates/frontend/layouts/base.html`

## Context Processor

Global template variables that don't change per-request:

```python
def config(_: Any) -> dict[str, Any]:
    return {
        "redirect_field_name": ProtectedView.redirect_field_name,
        "settings": {
            "SITE_NAME": settings.SITE_NAME,
            "CSRF_HEADER_NAME": ...,
            "CF_TURNSTILE": {...},
        },
    }
```

→ Example: `app/frontend/context_processors.py`

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

→ Implementation: `app/frontend/templatetags/frontend_tags.py` (`_enum_to_dict`,
`enums_json`), `app/frontend/static/frontend/js/utils.js` (`enumLabel`)

→ Usage: `app/frontend/templates/frontend/index.html`,
`app/frontend/templates/frontend/invitation-accept.html`

## Dark Mode

- Stored in `localStorage` with values: `light`, `dark`, `auto`.
- `auto` follows system preference via `prefers-color-scheme`.
- Applied by setting `data-bs-theme` attribute on `<html>`.
- Toggle in navbar with dropdown (Light, Dark, Auto options).

→ Example: `app/frontend/templates/frontend/components/navbar.html`

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

| Logic Type          | Location                                          |
|---------------------|---------------------------------------------------|
| Page-specific       | Inline `<script>` in template                     |
| Reusable components | `app/frontend/static/frontend/js/components/*.js` |
| Core utilities      | `app/frontend/static/frontend/js/api.js`          |
| Alpine stores       | `app/frontend/static/frontend/js/stores.js`       |

Inline scripts are not linted. Extract complex logic to `.js` files for linting.

## Coding Conventions

- Keep custom CSS minimal; use Bootstrap utilities.
- Use `x-cloak` to hide Alpine-controlled elements until initialization.
- Use `:key` with `x-for` loops for correct reactivity.
- Prefer `@mousedown.prevent` over `@click` when blur timing matters.
- Never use `x-show` on the same element as `d-flex` or other Bootstrap display
  utilities (`d-block`, `d-grid`, etc.). Bootstrap uses `!important` which overrides
  Alpine's inline `display: none`. Use `x-if` with `<template>` instead, or put `x-show`
  on a parent/wrapper.

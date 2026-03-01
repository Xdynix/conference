# Batch Import API Guide

## 1. Overview

This guide covers everything needed to write scripts that batch import papers and
reviews into a conference. The typical workflow is:

1. **Authenticate** with an API key to obtain a session.
2. **Create papers** with metadata (title, abstract, authors, keywords).
3. **Upload submission files** (PDF/DOCX) for each paper.
4. **Submit papers** to transition them from Draft to Submitted state.
5. **Import reviews** for each paper.

All endpoints are rooted at `https://<host>/api/`.

## 2. Prerequisites: Finding Configuration Values

Before scripting, gather the following values from the web UI:

- **Conference name** (slug): The URL-safe identifier visible in the browser address bar
  (e.g., `CBPK-2025` from `https://example.com/conference/CBPK-2025/`).
- **Track UID**: Not displayed in the web UI. Retrieve it by calling
  `GET /api/conferences/{conference_name}`, which returns a `tracks` array; each entry
  has a `uid` field (a ULID like `01J5ABCDEF...`) and a `display_name`. Alternatively,
  inspect network requests in your browser's developer tools.
- **Available keywords**: The same `GET /api/conferences/{conference_name}` response
  includes a `keywords` array of strings. The `keywords` field in Create Paper and
  Update Paper only accepts values from this list.
- **Paper codes**: Returned by the Create Paper endpoint (e.g., `PAPER-1001`). These are
  used in all subsequent calls for that paper.

## 3. Authentication

### Step 1: Generate an API key

Navigate to `/account/#api-key` in the web UI. You will be prompted to confirm your
password. The generated key has the prefix `cfk_` and is shown once; copy it
immediately.

### Step 2: Authenticate via API

```http request
POST /api/sessions/api-key
Content-Type: application/json
```

```json
{
  "key": "cfk_your_api_key_here"
}
```

The response sets two cookies:

- `sessionid` -- your session identifier.
- `csrftoken` -- the CSRF token required for all mutation requests.

Persist these cookies across requests (e.g., using a `requests.Session` in Python).

### CSRF handling

All `POST`, `PATCH`, `PUT`, and `DELETE` requests must include two things:

1. **CSRF token header.** Set `X-CSRFToken` to the value of the `csrftoken` cookie.
   The server compares the secret in the header against the secret in the cookie; both
   must be present and match.

2. **`Referer` header.** The server verifies that the request originates from the same
   host by checking the `Origin` or `Referer` header. The `requests` library does not
   send either by default, so scripts must set `Referer` explicitly (e.g.,
   `https://conference.example.com/`).

```text
X-CSRFToken: <value of csrftoken cookie>
Referer: https://<host>/
```

### Session lifetime

Sessions expire after **1 hour**. When a request returns `401`, re-authenticate by
calling the API key endpoint again.

## 4. Error Handling

### HTTP status codes

| Code | Meaning                                                |
|------|--------------------------------------------------------|
| 200  | Success                                                |
| 201  | Created                                                |
| 400  | Bad request (state violation, invalid operation)       |
| 401  | Unauthorized (session expired or missing)              |
| 403  | Forbidden (insufficient permissions or CSRF failure)   |
| 404  | Not found (conference, paper, or track does not exist) |
| 422  | Validation error (invalid field values)                |

### Error response format

All API errors follow this schema:

```json
{
  "message": "Human-readable error description.",
  "details": [
    {
      "loc": [
        "field_name"
      ],
      "msg": "Specific validation message."
    }
  ]
}
```

- `message` (string): Always present. Describes the error.
- `details` (array or null): Present for validation errors. Each entry has `loc` (field
  path) and `msg` (error message).

### Common error scenarios

- **CSRF failure** (403): The response body is HTML, not JSON. This means the
  `X-CSRFToken` header is missing or does not match the `csrftoken` cookie.
- **Session expired** (401): Re-authenticate with the API key endpoint.
- **State violation** (400): The paper is not in the required state for the operation
  (e.g., trying to submit a paper that is not in Draft state).

## 5. Endpoint Reference

All endpoints require the session cookies (`sessionid`, `csrftoken`), the `X-CSRFToken`
header, and the `Referer` header as described in section 3. JSON endpoints use
`Content-Type: application/json`; the Upload Submission endpoint uses
`Content-Type: multipart/form-data` instead.

### 5.1. Create Paper

```http request
POST /api/conferences/{conference_name}/papers
```

Creates a paper as an admin. The paper is created in Draft state with an auto-assigned
code from the track's code pool. Bypasses the track's submissions-enabled check,
allowing creation of invited papers or papers for tracks not currently open.

**Request body:**

```json
{
  "track": "01J5ABCDEF...",
  "title": "My Paper Title",
  "abstract": "Paper abstract supporting formatted text.",
  "contribution": "Description of the contribution.",
  "keywords": [
    "machine learning",
    "optimization"
  ],
  "authors": [
    {
      "given_name": "John",
      "family_name": "Doe",
      "affiliation": "MIT",
      "region_code": "US",
      "email": "john@example.com",
      "phone": "+1234567890",
      "corresponding": true
    },
    {
      "given_name": "Jane",
      "family_name": "Smith",
      "affiliation": "Stanford",
      "region_code": "US",
      "email": "jane@example.com",
      "phone": "",
      "corresponding": false
    }
  ],
  "auto_claim": false
}
```

- `track` (string, **required**) -- ULID of the target track within the conference.
- `title` (string, **required**) -- Sanitized, whitespace-trimmed.
- `abstract` (string) -- Supports formatted text. Default: `""`.
- `contribution` (string) -- Supports formatted text. Default: `""`.
- `keywords` (array of strings) -- Values must come from the conference's keyword list
  (see section 2). Default: `[]`.
- `authors` (array of objects) -- Default: `[]`. Each author object:
    - `given_name` (string) -- Default: `""`.
    - `family_name` (string) -- Default: `""`.
    - `affiliation` (string) -- Default: `""`.
    - `region_code` (string) -- ISO region code (e.g., `"US"`, `"GB"`) or `""`. Default:
      `""`.
    - `email` (string) -- Valid email or `""`. Default: `""`.
    - `phone` (string) -- Default: `""`.
    - `corresponding` (boolean) -- Default: `false`.
- `auto_claim` (boolean) -- Papers created by an admin are owned by that admin. If
  `true`, the system marks the paper for ownership transfer to the corresponding
  author's email, so the author can later claim the paper and perform actions that
  require ownership (e.g., uploading a final revision). Requires exactly one
  corresponding author with an email. Default: `false`.

**Response** (`201 Created`):

```json
{
  "uid": "01J5A...",
  "conference": "CBPK-2025",
  "track": {
    "uid": "01J5A...",
    "display_name": "Regular"
  },
  "code": "PAPER-1001",
  "create_time": "2025-06-01T12:00:00Z",
  "state": "Draft",
  "title": "My Paper Title",
  "abstract": "Paper abstract supporting formatted text.",
  "contribution": "Description of the contribution.",
  "keywords": [
    "machine learning",
    "optimization"
  ],
  "authors": [
    {
      "given_name": "John",
      "family_name": "Doe",
      "affiliation": "MIT",
      "region_code": "US",
      "email": "john@example.com",
      "phone": "+1234567890",
      "corresponding": true
    }
  ],
  "submission": null,
  "final": null,
  "final_revision_remaining": 1,
  "owner": {
    "uid": "01J5A...",
    "email": "admin@example.com",
    "profile": {
      "...": "..."
    }
  }
}
```

The `code` field in the response is the auto-assigned paper code used in all subsequent
requests.

**Notes:**

- The paper is always created in `Draft` state.
- The `code` is auto-assigned from the track's code pool. If the track has no code pool,
  a 422 error is returned.
- Keywords must come from the conference's keyword list (returned by
  `GET /api/conferences/{conference_name}`); unknown values produce a 422 error.
- When `auto_claim` is `true` but the authors do not contain exactly one corresponding
  author with a valid email, a 422 error is returned.

### 5.2. Update Paper

```http request
PATCH /api/conferences/{conference_name}/papers/{paper_code}
```

Updates paper metadata, authors, and keywords. All fields are optional (PATCH
semantics). When provided, `authors` and `keywords` replace existing values entirely (
not merged).

**Request body:**

Only include the fields you want to update.

```json
{
  "title": "Updated Paper Title",
  "abstract": "Updated abstract text.",
  "contribution": "Updated contribution.",
  "keywords": [
    "machine learning",
    "NLP"
  ],
  "authors": [
    {
      "given_name": "John",
      "family_name": "Doe",
      "affiliation": "University of Oxford",
      "region_code": "GB",
      "email": "john@example.com",
      "phone": "+1234567890",
      "corresponding": true
    }
  ]
}
```

- `title` (string) -- Sanitized.
- `abstract` (string) -- Supports formatted text.
- `contribution` (string) -- Supports formatted text.
- `keywords` (array of strings) -- Values must come from the conference's keyword list
  (see section 2). Replaces all existing keywords.
- `authors` (array of objects) -- Same structure as Create Paper. Replaces all existing
  authors.

**Response** (`200 OK`):

Same structure as Create Paper response, reflecting the updated values.

**Notes:**

- Track admins can update papers in Draft, Submitted, or Under Review state only.
  Conference admins can update papers in any state except Withdrawn.
- Withdrawn papers cannot be updated regardless of role.
- If the paper was marked for ownership transfer (via `auto_claim` at creation) and the
  updated authors change the corresponding author's email, the pending transfer is
  cancelled.

### 5.3. Upload Submission

```http request
POST /api/conferences/{conference_name}/papers/{paper_code}/submissions
```

Uploads a submission file for a paper. Creates a new revision of the submission. Admin
uploads preserve all revisions.

**Request body (multipart form):**

- `file` (file, **required**) -- PDF (`.pdf`), DOCX (`.docx`), or DOC (`.doc`).

**Response** (`201 Created`):

```json
{
  "uid": "01HQ...",
  "conference": "CBPK-2025",
  "track": {
    "uid": "01HQ...",
    "display_name": "Regular"
  },
  "code": "PAPER-1001",
  "state": "Draft",
  "title": "My Paper Title",
  "submission": {
    "uid": "01HQ...",
    "display_name": "PAPER-1001.pdf",
    "download_url": "https://example.com/api/submissions/01HQ.../PAPER-1001.pdf"
  },
  "...": "..."
}
```

**Notes:**

- Allowed file types are validated by content detection (not just extension). The file's
  detected MIME type must match its extension.
- Track admins can upload to papers in Draft, Submitted, or Under Review state.
  Conference admins can upload to papers in any state except Withdrawn.
- The `submission` field in the response contains the latest uploaded file's metadata
  and download URL.

### 5.4. Submit Paper

```http request
POST /api/conferences/{conference_name}/papers/{paper_code}:submit
```

Transitions a paper from Draft to Submitted state. The admin variant uses non-strict
validation: only the title is required (no submission file, authors, or abstract
required).

**Request body:** None (empty body).

**Response** (`200 OK`):

```json
{
  "uid": "01HQ...",
  "conference": "CBPK-2025",
  "code": "PAPER-1001",
  "state": "Submitted",
  "submit_time": "2025-06-01T14:00:00Z",
  "title": "My Paper Title",
  "...": "..."
}
```

**Notes:**

- The paper must be in `Draft` state. Submitting from any other state returns 400.
- Withdrawn papers cannot be submitted.
- The admin endpoint only validates that `title` is non-empty. A submission file is not
  required (unlike the author endpoint which enforces full validation).

### 5.5. Import Review

```http request
POST /api/conferences/{conference_name}/papers/{paper_code}/reviews:import
```

Creates or updates an imported review. The review is created with no assigned reviewer
(offline review) and immediately placed in Submitted state. If `offline_reviewer_name`is
provided and a review with that same name already exists for the paper, the existing
review is updated instead of creating a duplicate.

**Request body:**

```json
{
  "offline_reviewer_name": "Dr. Jane Smith",
  "originality": 4,
  "significance": 3,
  "technical": 5,
  "reference": 4,
  "presentation": 3,
  "match_topic": 4,
  "recommendation": 5,
  "contribution": "The paper presents a novel approach...",
  "decision_reason": "Strong theoretical foundation...",
  "comments": "Consider expanding the related work section.",
  "confidential_remarks": "Minor concerns about originality."
}
```

- `offline_reviewer_name` (string) -- Display name for the external reviewer. When
  non-empty, enables upsert behavior (see notes). Default: `""`.
- `originality` (integer) -- 1 to 5. Default: `null`.
- `significance` (integer) -- 1 to 5. Default: `null`.
- `technical` (integer) -- 1 to 5. Default: `null`.
- `reference` (integer) -- 1 to 5. Default: `null`.
- `presentation` (integer) -- 1 to 5. Default: `null`.
- `match_topic` (integer) -- 1 to 5. Default: `null`.
- `recommendation` (integer) -- 1 to 5. Default: `null`.
- `contribution` (string) -- Supports formatted text. Default: `""`.
- `decision_reason` (string) -- Supports formatted text. Default: `""`.
- `comments` (string) -- Suggestions for the authors. Default: `""`.
- `confidential_remarks` (string) -- Visible only to editors. Default: `""`.

**Response** (`201 Created` for new review, `200 OK` for update):

```json
{
  "uid": "01HQ...",
  "create_time": "2025-06-15T10:30:00Z",
  "paper": {
    "uid": "01HQ...",
    "conference": "CBPK-2025",
    "track": {
      "uid": "01HQ...",
      "display_name": "Regular"
    },
    "code": "PAPER-1001",
    "title": "A Novel Approach to...",
    "abstract": "This paper presents...",
    "keywords": [
      "blockchain",
      "consensus"
    ],
    "submission": {
      "uid": "01HQ...",
      "display_name": "PAPER-1001.pdf",
      "download_url": "https://example.com/api/submissions/01HQ.../PAPER-1001.pdf"
    }
  },
  "state": "Submitted",
  "recommendation": 5,
  "submit_time": "2025-06-15T10:30:00Z",
  "reviewer": null,
  "offline_reviewer_name": "Dr. Jane Smith",
  "assigner": {
    "uid": "01HQ...",
    "email": "admin@example.com",
    "profile": {
      "given_name": "Admin",
      "family_name": "User",
      "affiliation": "",
      "region_code": ""
    }
  },
  "originality": 4,
  "significance": 3,
  "technical": 5,
  "reference": 4,
  "presentation": 3,
  "match_topic": 4,
  "contribution": "The paper presents a novel approach...",
  "decision_reason": "Strong theoretical foundation...",
  "comments": "Consider expanding the related work section.",
  "confidential_remarks": "Minor concerns about originality."
}
```

**Notes:**

- Requires Global Admin or Conference Admin role. Track Admin is not sufficient.
- **Upsert behavior:** When `offline_reviewer_name` is non-empty, the endpoint uses
  update-or-create semantics keyed on `(paper, reviewer=null, offline_reviewer_name)`.
  When `offline_reviewer_name` is empty or omitted, a new review is always created.
- All score fields are constrained to integers 1 to 5.
- Text fields are sanitized as formatted text.

## 6. Complete Example Script

The following Python script demonstrates a batch workflow: authenticate, create papers,
upload submissions, submit them, and import reviews. It uses a hardcoded list of paper
data as a placeholder; replace it with your own data-loading logic (e.g., from CSV or
Excel).

```python
"""Batch import papers and reviews via the conference API."""

import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration -- adjust these values for your environment
# ---------------------------------------------------------------------------

BASE_URL = "https://conference.example.com/api"
API_KEY = "cfk_your_api_key_here"
CONFERENCE = "CBPK-2025"
TRACK_UID = "01J5ABCDEF0000000000000000"

# Paper data to import. Replace with your own data-loading logic.
PAPERS = [
    {
        "title": "A Novel Approach to Distributed Consensus",
        "abstract": "We present a new consensus algorithm...",
        "keywords": ["distributed systems", "consensus"],
        "authors": [
            {
                "given_name": "Alice",
                "family_name": "Chen",
                "affiliation": "MIT",
                "region_code": "US",
                "email": "alice@example.com",
                "corresponding": True,
            },
            {
                "given_name": "Bob",
                "family_name": "Lee",
                "affiliation": "Stanford",
                "region_code": "US",
                "email": "bob@example.com",
                "corresponding": False,
            },
        ],
        "submission_file": "papers/paper1.pdf",
        "reviews": [
            {
                "offline_reviewer_name": "Reviewer A",
                "recommendation": 4,
                "originality": 4,
                "significance": 3,
                "technical": 5,
                "comments": "Well-written paper with solid experiments.",
            },
            {
                "offline_reviewer_name": "Reviewer B",
                "recommendation": 3,
                "originality": 3,
                "significance": 3,
                "technical": 4,
                "comments": "The related work section needs expansion.",
            },
        ],
    },
    {
        "title": "Efficient Graph Neural Networks for Large-Scale Data",
        "abstract": "This work proposes a scalable GNN architecture...",
        "keywords": ["graph neural networks", "scalability"],
        "authors": [
            {
                "given_name": "Carol",
                "family_name": "Wang",
                "affiliation": "ETH Zurich",
                "region_code": "CH",
                "email": "carol@example.com",
                "corresponding": True,
            },
        ],
        "submission_file": "papers/paper2.pdf",
        "reviews": [
            {
                "offline_reviewer_name": "Reviewer C",
                "recommendation": 5,
                "originality": 5,
                "significance": 4,
                "technical": 5,
                "comments": "Excellent contribution to the field.",
            },
        ],
    },
    {
        "title": "Privacy-Preserving Machine Learning: A Survey",
        "abstract": "We survey recent advances in privacy-preserving ML...",
        "keywords": ["privacy", "machine learning"],
        "authors": [
            {
                "given_name": "David",
                "family_name": "Kim",
                "affiliation": "University of Tokyo",
                "region_code": "JP",
                "email": "david@example.com",
                "corresponding": True,
            },
        ],
        "submission_file": "papers/paper3.pdf",
        "reviews": [],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_url(path: str) -> str:
    """Build a full API URL from a relative path."""
    return f"{BASE_URL}/{path.lstrip('/')}"


def mutation_headers(session: requests.Session) -> dict[str, str]:
    """Headers required for all mutation requests (CSRF token + Referer)."""
    token = session.cookies.get("csrftoken", "")
    return {"X-CSRFToken": token, "Referer": BASE_URL + "/"}


def check_response(resp: requests.Response, context: str) -> dict | None:
    """Check response status and return JSON body, or exit on failure."""
    if resp.ok:
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return None

    print(f"  ERROR [{resp.status_code}] {context}")
    try:
        error = resp.json()
        print(f"  Message: {error.get('message', 'N/A')}")
        if error.get("details"):
            for detail in error["details"]:
                print(f"    - {detail.get('loc', '?')}: {detail.get('msg', '?')}")
    except Exception:
        print(f"  Body: {resp.text[:500]}")
    return None


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------


def authenticate(session: requests.Session) -> bool:
    """Authenticate with the API key and return True on success."""
    resp = session.post(
        api_url("/sessions/api-key"),
        json={"key": API_KEY},
    )
    if not resp.ok:
        print(f"Authentication failed [{resp.status_code}]: {resp.text[:200]}")
        return False
    print("Authenticated successfully.")
    return True


def create_paper(session: requests.Session, paper_data: dict) -> str | None:
    """Create a paper and return its code, or None on failure."""
    payload = {
        "track": TRACK_UID,
        "title": paper_data["title"],
        "abstract": paper_data.get("abstract", ""),
        "keywords": paper_data.get("keywords", []),
        "authors": paper_data.get("authors", []),
    }
    if paper_data.get("contribution"):
        payload["contribution"] = paper_data["contribution"]

    resp = session.post(
        api_url(f"/conferences/{CONFERENCE}/papers"),
        json=payload,
        headers=mutation_headers(session),
    )
    result = check_response(resp, f"Create paper '{paper_data['title'][:40]}'")
    if result is None:
        return None
    code = result["code"]
    print(f"  Created paper {code}")
    return code


def upload_submission(
    session: requests.Session, paper_code: str, file_path: str
) -> bool:
    """Upload a submission file for a paper. Returns True on success."""
    path = Path(file_path)
    if not path.exists():
        print(f"  SKIP upload: file not found: {file_path}")
        return False

    with path.open("rb") as f:
        resp = session.post(
            api_url(f"/conferences/{CONFERENCE}/papers/{paper_code}/submissions"),
            files={"file": (path.name, f, "application/pdf")},
            headers=mutation_headers(session),
        )
    result = check_response(resp, f"Upload submission for {paper_code}")
    if result is None:
        return False
    print(f"  Uploaded submission for {paper_code}")
    return True


def submit_paper(session: requests.Session, paper_code: str) -> bool:
    """Submit a paper (Draft -> Submitted). Returns True on success."""
    resp = session.post(
        api_url(f"/conferences/{CONFERENCE}/papers/{paper_code}:submit"),
        headers=mutation_headers(session),
    )
    result = check_response(resp, f"Submit {paper_code}")
    if result is None:
        return False
    print(f"  Submitted {paper_code}")
    return True


def import_review(
    session: requests.Session, paper_code: str, review_data: dict
) -> bool:
    """Import a single review for a paper. Returns True on success."""
    resp = session.post(
        api_url(f"/conferences/{CONFERENCE}/papers/{paper_code}/reviews:import"),
        json=review_data,
        headers=mutation_headers(session),
    )
    reviewer = review_data.get("offline_reviewer_name", "anonymous")
    result = check_response(resp, f"Import review by '{reviewer}' for {paper_code}")
    if result is None:
        return False
    print(f"  Imported review by '{reviewer}' for {paper_code}")
    return True


def main() -> None:
    session = requests.Session()

    if not authenticate(session):
        sys.exit(1)

    success_count = 0
    fail_count = 0

    for paper_data in PAPERS:
        print(f"\nProcessing: {paper_data['title'][:60]}...")

        # 1. Create paper
        paper_code = create_paper(session, paper_data)
        if paper_code is None:
            fail_count += 1
            continue

        # 2. Upload submission file (if provided)
        if paper_data.get("submission_file"):
            upload_submission(session, paper_code, paper_data["submission_file"])

        # 3. Submit paper
        if not submit_paper(session, paper_code):
            fail_count += 1
            continue

        # 4. Import reviews
        for review in paper_data.get("reviews", []):
            import_review(session, paper_code, review)

        success_count += 1

    print(f"\nDone. {success_count} succeeded, {fail_count} failed.")


if __name__ == "__main__":
    main()
```

### Script notes

- **Session management:** The `requests.Session` object automatically persists cookies
  (`sessionid` and `csrftoken`) across requests.
- **CSRF and Referer:** The `mutation_headers()` helper includes both the `X-CSRFToken`
  header (from the cookie jar) and the `Referer` header (derived from `BASE_URL`). The
  server requires both.
- **Error handling:** The script prints errors and continues to the next paper. Adapt
  the `check_response()` function for your needs (e.g., raise exceptions, retry on 401).
- **Re-authentication:** For large batches, add a check for 401 responses and call
  `authenticate()` again before retrying the failed request.
- **File paths:** The `submission_file` field expects a path relative to the script's
  working directory. Adjust for your file organization.

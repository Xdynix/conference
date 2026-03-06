# Email Sending API Guide

## 1. Overview

This guide covers writing scripts that send emails through the conference system. A
typical workflow is:

1. **Authenticate** with an API key.
2. **Upload conference files** for any static attachments (PDFs, forms, etc.).
3. **Fetch data** (papers, registrations) to determine recipients and content.
4. **Send emails** with optional attachments (conference files, acceptance letters,
   receipts, or inline content).

All endpoints are rooted at `https://<host>/api/`.

## 2. Prerequisites

Before scripting, gather the following value:

- **Conference name** (slug): The URL-safe identifier visible in the browser address bar
  (e.g., `CBPK-2025` from `https://example.com/conference/CBPK-2025/`).

## 3. Authentication

### Step 1: Generate an API key

Navigate to `/account/#api-key` in the web UI. Confirm your password to generate a key
with the prefix `cfk_`. The key is shown once; copy it immediately.

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

All `POST`, `PATCH`, `PUT`, and `DELETE` requests require:

1. **`X-CSRFToken` header** set to the value of the `csrftoken` cookie.
2. **`Referer` header** set to the host URL (e.g., `https://conference.example.com/`).

```text
X-CSRFToken: <value of csrftoken cookie>
Referer: https://<host>/
```

### Session lifetime

Sessions expire after **1 hour**. When a request returns `401`, re-authenticate by
calling the API key endpoint again.

## 4. Error Handling

### HTTP status codes

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 200  | Success                                              |
| 201  | Created                                              |
| 400  | Bad request (state violation, invalid operation)     |
| 401  | Unauthorized (session expired or missing)            |
| 403  | Forbidden (insufficient permissions or CSRF failure) |
| 404  | Not found                                            |
| 422  | Validation error (invalid field values)              |

### Error response format

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

- `message` (string): Always present.
- `details` (array or null): Present for validation errors. Each entry has `loc` (field
  path) and `msg` (error message).

### Common error scenarios

- **CSRF failure** (403): The response body is HTML, not JSON. This means the
  `X-CSRFToken` header is missing or does not match the `csrftoken` cookie.
- **Session expired** (401): Re-authenticate by calling the API key endpoint again.
- **Attachment not found** (422): The referenced acceptance letter, receipt, or
  conference file does not exist or is not in the required state (e.g., the paper is not
  accepted, the receipt has not been generated). Acceptance letters and receipts are
  generated through the admin panel; their availability is typically visible in the
  paper or registration response.

## 5. Conference Files

Conference files are shared files (PDF forms, instruction documents, etc.) that can be
attached to emails by name. Upload them before sending emails that reference them.

### Upload (create or replace)

```http request
POST /api/conferences/{conference_name}/files/{file_name}:upload
Content-Type: multipart/form-data
```

- `{file_name}` is a slug you choose (e.g., `registration-procedure`). Re-uploading the
  same name replaces the file.
- Form field: `file` -- the file to upload.
- Maximum size: 10 MB.
- Allowed types: PDF, DOCX, DOC, XLSX, XLS, PNG, JPG/JPEG.

**Response** (`201 Created` for new, `200 OK` for replacement):

```json
{
  "name": "registration-procedure",
  "filename": "Registration_Procedure.pdf",
  "size": 204800,
  "create_time": "2025-06-01T12:00:00Z",
  "update_time": "2025-06-01T12:00:00Z"
}
```

### List files

```http request
GET /api/conferences/{conference_name}/files
```

Returns an array of conference file objects (same structure as above).

## 6. Send Email

```http request
POST /api/conferences/{conference_name}/emails:send
Content-Type: application/json
```

Sends a single email with optional attachments.

### Request body

```json
{
  "correlation_id": "acceptance-letter:PAPER-1001",
  "force": false,
  "to": [
    "author@example.com"
  ],
  "subject": "Your paper has been accepted",
  "body": "Dear author,\n\nWe are pleased to inform you...",
  "format": "text",
  "from_name": "CBPK 2025 Committee",
  "cc": [],
  "bcc": [],
  "reply_to": "chair@example.com",
  "attachments": []
}
```

**Fields:**

- `correlation_id` (string, **required**, max 255 characters) -- Caller-defined
  identifier for idempotency and log correlation. Use a pattern like
  `"acceptance-letter:{paper_code}"` or `"receipt:{registration_uid}"` to make IDs
  meaningful and unique per logical operation.
- `force` (boolean) -- When `false` (default), a request with a previously used
  `correlation_id` returns `200` with `sent: false` instead of dispatching the email
  again. Set to `true` to force a resend.
- `to` (array of emails, **required**) -- 1 to 100 recipients.
- `subject` (string, **required**) -- Max 998 characters.
- `body` (string, **required**) -- Max 100,000 characters.
- `format` (`"text"` or `"html"`) -- Default: `"text"`.
- `from_name` (string) -- Display name for the sender. The sending address is always the
  system's configured address; only the display name can be customized.
- `cc` (array of emails) -- Default: `[]`.
- `bcc` (array of emails) -- Default: `[]`.
- `reply_to` (email or null) -- Default: `null`.
- `attachments` (array) -- Up to 20 attachment references. See section 6.1.

### Response

```json
{
  "sent": true,
  "correlation_id": "acceptance-letter:PAPER-1001",
  "send_time": "2025-06-01T12:30:00Z"
}
```

- `sent` (boolean) -- `true` if the email was dispatched, `false` if skipped due to
  idempotency (same `correlation_id` without `force`).
- `correlation_id` (string) -- Echoed back for log correlation.
- `send_time` (datetime) -- When the email was last sent.

### 6.1. Attachment Types

Each attachment is a JSON object with a `type` field that determines its structure. Four
types are supported:

#### `conference_file` -- Reference a shared conference file by name

```json
{
  "type": "conference_file",
  "name": "registration-procedure",
  "filename": "Registration_Procedure.pdf"
}
```

- `name` (string, **required**) -- The slug used when uploading the file.
- `filename` (string) -- Override the download filename. If omitted, the original upload
  filename is used.

#### `acceptance_letter` -- Reference a generated acceptance letter for a paper

```json
{
  "type": "acceptance_letter",
  "paper_code": "PAPER-1001",
  "filename": "Acceptance_Letter_PAPER-1001.pdf"
}
```

- `paper_code` (string, **required**) -- The paper must be in an accepted state with a
  generated acceptance letter.
- `filename` (string) -- Override the download filename.

#### `receipt` -- Reference a generated receipt for a registration

```json
{
  "type": "receipt",
  "registration_uid": "01J5ABCDEF...",
  "filename": "Receipt.pdf"
}
```

- `registration_uid` (string, **required**) -- The registration must not be cancelled
  and must have a generated receipt.
- `filename` (string) -- Override the download filename.

#### `inline` -- Embed file content directly (base64)

Use this for files generated locally by your script (e.g., per-recipient certificates or
personalized schedules) rather than stored on the server as conference files.

```json
{
  "type": "inline",
  "filename": "schedule.pdf",
  "content": "<base64-encoded bytes>"
}
```

- `filename` (string, **required**) -- The attachment filename.
- `content` (string, **required**) -- Base64-encoded file content. Max 10 MB decoded.

## 7. Useful Endpoints for Data Fetching

Email scripts typically need to fetch data to determine recipients and compose messages.
The endpoints below cover the most common needs. Make a `GET` request to explore the
response structure; all return JSON.

<!-- markdownlint-disable MD013 -->

### Papers

| Endpoint                                                            | Description                               |
|---------------------------------------------------------------------|-------------------------------------------|
| `GET /api/conferences/{conference_name}/papers`                     | List all papers (supports query filters). |
| `GET /api/conferences/{conference_name}/papers/{paper_code}`        | Get a single paper with full detail.      |
| `GET /api/conferences/{conference_name}/papers/-/acceptance-letter` | List generated acceptance letters.        |

Key paper fields for email scripting: `code`, `state` (e.g., `"Accepted"`,
`"Accepted (Revision Needed)"`), `announce_time` (non-null when the decision has been
communicated to the author), `withdrawn_time` (non-null for withdrawn papers), `authors`
(array with `email`, `given_name`, `family_name`, `corresponding`), `title`, `track`.

### Registrations

| Endpoint                                                                  | Description                |
|---------------------------------------------------------------------------|----------------------------|
| `GET /api/conferences/{conference_name}/registrations`                    | List all registrations.    |
| `GET /api/conferences/{conference_name}/registrations/{registration_uid}` | Get a single registration. |
| `GET /api/conferences/{conference_name}/registrations/-/receipt`          | List generated receipts.   |

### Conference Metadata

| Endpoint                                       | Description                                     |
|------------------------------------------------|-------------------------------------------------|
| `GET /api/conferences/{conference_name}`       | Conference detail (tracks, keywords, settings). |
| `GET /api/conferences/{conference_name}/files` | List uploaded conference files.                 |

<!-- markdownlint-enable MD013 -->

To discover the full response structure of any endpoint, make a request and inspect the
JSON. Fields use `snake_case` naming; IDs are ULIDs (26-character strings); datetimes
are ISO 8601 with timezone.

### Pagination

Some list endpoints return paginated responses. A paginated response has this shape:

```json
{
  "items": [],
  "next_page_token": "..."
}
```

When `next_page_token` is non-null, pass it as `?page_token=<value>` to fetch the next
page. You can also set `?page_size=<n>` to control the number of items per page (the
maximum varies by endpoint). Not all list endpoints are paginated; probe the response
structure to determine whether a given endpoint returns a flat array or a paginated
object.

## 8. Example: Send Acceptance Letters

The following script demonstrates a common workflow: upload a static attachment (
registration procedure PDF), fetch accepted papers, and send each corresponding author
an email with the acceptance letter and the registration procedure attached.

```python
"""Send acceptance letters with registration procedure to accepted paper authors."""

import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://conference.example.com/api"
API_KEY = "cfk_your_api_key_here"
CONFERENCE = "CBPK-2025"

# Path to the registration procedure PDF to attach.
REGISTRATION_PROCEDURE_PATH = "Registration_Procedure.pdf"
# Slug under which the file will be stored on the server.
REGISTRATION_PROCEDURE_NAME = "registration-procedure"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_url(path: str) -> str:
    """Build a full API URL from a relative path."""
    return f"{BASE_URL}/{path.lstrip('/')}"


def mutation_headers(session: requests.Session) -> dict[str, str]:
    """Headers required for all mutation requests (CSRF + Referer)."""
    token = session.cookies.get("csrftoken", "")
    return {"X-CSRFToken": token, "Referer": BASE_URL + "/"}


def check_response(resp: requests.Response, context: str) -> dict | list | None:
    """Check response status and return JSON body, or None on failure."""
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
# Steps
# ---------------------------------------------------------------------------


def authenticate(session: requests.Session) -> bool:
    """Authenticate and return True on success."""
    resp = session.post(api_url("/sessions/api-key"), json={"key": API_KEY})
    if not resp.ok:
        print(f"Authentication failed [{resp.status_code}]: {resp.text[:200]}")
        return False
    print("Authenticated successfully.")
    return True


def upload_registration_procedure(session: requests.Session) -> bool:
    """Upload the registration procedure PDF as a conference file."""
    path = Path(REGISTRATION_PROCEDURE_PATH)
    if not path.exists():
        print(f"File not found: {path}")
        return False

    with path.open("rb") as f:
        resp = session.post(
            api_url(
                f"/conferences/{CONFERENCE}"
                f"/files/{REGISTRATION_PROCEDURE_NAME}:upload"
            ),
            files={"file": (path.name, f, "application/pdf")},
            headers=mutation_headers(session),
        )

    result = check_response(resp, "Upload registration procedure")
    if result is None:
        return False

    status = "replaced" if resp.status_code == 200 else "created"
    print(f"Registration procedure {status}: {result['filename']}")
    return True


def fetch_papers(session: requests.Session) -> list[dict]:
    """Fetch all papers for the conference, handling pagination."""
    papers: list[dict] = []
    url = api_url(f"/conferences/{CONFERENCE}/papers?page_size=500")
    while url:
        resp = session.get(url)
        result = check_response(resp, "Fetch papers")
        if result is None:
            return papers
        papers.extend(result["items"])
        next_token = result.get("next_page_token")
        if next_token:
            url = api_url(
                f"/conferences/{CONFERENCE}/papers"
                f"?page_size=500&page_token={next_token}"
            )
        else:
            url = ""
    return papers


def send_acceptance_email(
    session: requests.Session,
    paper: dict,
    author_email: str,
    author_name: str,
) -> bool:
    """Send an acceptance letter email for a single paper."""
    paper_code = paper["code"]
    payload = {
        "correlation_id": f"acceptance-letter:{paper_code}",
        "to": [author_email],
        "subject": f"[{CONFERENCE}] Acceptance Notification - {paper_code}",
        "body": (
            f"Dear {author_name},\n\n"
            f"We are pleased to inform you that your paper "
            f"\"{paper['title']}\" ({paper_code}) has been accepted "
            f"to {CONFERENCE}.\n\n"
            f"Please find attached your acceptance letter and the "
            f"registration procedure.\n\n"
            f"Best regards,\n"
            f"{CONFERENCE} Organizing Committee"
        ),
        "attachments": [
            {
                "type": "acceptance_letter",
                "paper_code": paper_code,
            },
            {
                "type": "conference_file",
                "name": REGISTRATION_PROCEDURE_NAME,
            },
        ],
    }

    resp = session.post(
        api_url(f"/conferences/{CONFERENCE}/emails:send"),
        json=payload,
        headers=mutation_headers(session),
    )
    result = check_response(resp, f"Send email for {paper_code}")
    if result is None:
        return False

    if result["sent"]:
        print(f"  Sent acceptance letter for {paper_code} to {author_email}")
    else:
        print(f"  Skipped {paper_code} (already sent)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    session = requests.Session()

    if not authenticate(session):
        sys.exit(1)

    # 1. Upload the registration procedure PDF (creates or replaces).
    if not upload_registration_procedure(session):
        sys.exit(1)

    # 2. Fetch all papers.
    papers = fetch_papers(session)
    if not papers:
        print("No papers found.")
        return

    # 3. Filter to accepted papers whose decisions have been announced.
    accepted_states = {"Accepted", "Accepted (Revision Needed)"}
    accepted_papers = [
        p for p in papers
        if p["state"] in accepted_states and p.get("announce_time")
    ]
    print(f"\nFound {len(accepted_papers)} accepted and announced papers.")

    # 4. Send acceptance letters.
    sent = 0
    failed = 0
    for paper in accepted_papers:
        # Find the corresponding author.
        corresponding = [a for a in paper.get("authors", []) if a["corresponding"]]
        if not corresponding:
            print(f"  SKIP {paper['code']}: no corresponding author.")
            failed += 1
            continue

        author = corresponding[0]
        email = author.get("email", "")
        if not email:
            print(f"  SKIP {paper['code']}: corresponding author has no email.")
            failed += 1
            continue

        name = f"{author.get('given_name', '')} {author.get('family_name', '')}".strip()
        if send_acceptance_email(session, paper, email, name or "Author"):
            sent += 1
        else:
            failed += 1

    print(f"\nDone. {sent} sent, {failed} failed/skipped.")


if __name__ == "__main__":
    main()
```

### Script notes

- **Test before sending:** For your first run, limit to a single paper (e.g., add
  `if paper_code != "PAPER-1001": continue` in the loop) and override the `to` field
  with your own email. Verify the subject, body, and all attachments arrive correctly
  before removing the overrides.
- **Idempotency:** The `correlation_id` is set to `"acceptance-letter:{paper_code}"`, so
  running the script again skips papers that were already emailed (the server returns
  `sent: false` with a 200 response). This means you do not need to maintain a local
  "sent log"; the server tracks what has already been dispatched. However, the
  `correlation_id` format must remain stable across runs. If you change the pattern (
  e.g., from `"acceptance-letter:..."` to `"acceptance_letter:..."`) the server treats
  it as a new email. This also applies when multiple admins run scripts independently;
  agree on a shared format.
- **Forcing resend:** Setting `"force": true` bypasses the idempotency check and resends
  the email unconditionally. Only use this for targeted resends of specific emails.
  Never set it as a default in a batch script; running the script twice would send
  duplicate emails to every recipient.
- **Customization:** Adjust the email body, subject, and attachment list for your needs.
  For HTML emails, set `"format": "html"` and write HTML in the `body` field.
- **Multiple recipients:** To CC or BCC additional people, add emails to the `cc` or
  `bcc` arrays.
- **Adapt the script:** This example is illustrative. For production use, adapt the
  error handling, add session re-authentication on 401 responses, and adjust the
  filtering logic to match your specific requirements.

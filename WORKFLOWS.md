# Workflows

This document describes the system's major user-facing workflows (happy paths only).

## Conventions

- **Actor roles:** Global Admin (superuser or global admin role), Conference
  Chair/Secretary (conference-level admins), Track Chair/Secretary (track-level admins),
  Reviewer, Author, User (any authenticated user).
- **State transitions** use arrow notation: `DRAFT -> SUBMITTED`.
- **Cross-references** link to other workflows with `(see §N: Name)`.

## State Machine Reference

### Paper

```text
DRAFT -> SUBMITTED -> UNDER_REVIEW -> ACCEPTED
                                   -> ACCEPTED_REVISION_NEEDED
                                   -> REJECTED
```

- `SUBMITTED -> DRAFT` (unsubmit, author only).
- `SUBMITTED` transitions to `UNDER_REVIEW` when the first reviewer is assigned.
- Any state can become `Withdrawn` (terminal flag, not a formal state).
- Decided states: `ACCEPTED`, `ACCEPTED_REVISION_NEEDED`, `REJECTED`.
- Authors see `UNDER_REVIEW` until the decision is announced, even if a decision exists.

### Review

```text
PENDING -> ACCEPTED -> SUBMITTED
PENDING -> DECLINED (terminal)
Any active state -> CANCELLED (terminal)
```

- Active states: `PENDING`, `ACCEPTED`, `SUBMITTED`.
- Admin can return a submitted review for revision (`SUBMITTED` back to `ACCEPTED`).

### Registration

```text
PENDING -> CONFIRMED
PENDING -> CANCELLED (terminal)
```

### Invitation

```text
PENDING -> ACCEPTED (terminal)
PENDING -> REJECTED
REJECTED -> ACCEPTED (via redemption, terminal)
```

## Dependency Map

```text
Conference Setup
├── Create Conference (§1)
│   ├── Create Tracks & Code Pools (§1)
│   ├── Configure Attendance Types (§1)
│   └── Invite Members (§1) ──> Account & Auth (§2)
│
├── Paper Lifecycle (§3)
│   ├── requires: tracks with code pools, authenticated author
│   └── Author creates -> submits -> paper enters review pipeline
│
├── Review Lifecycle (§4)
│   ├── requires: submitted papers, assigned reviewers
│   └── Assign -> accept -> submit review
│
├── Decisions & Announcements (§5)
│   ├── requires: submitted papers (optionally with reviews)
│   └── Decide -> generate letter (accepted) -> announce
│
├── Registration & Payments (§6)
│   ├── requires: attendance types, announced/accepted paper (if paper required)
│   └── Register -> confirm -> record payment -> generate receipt
│
├── Proof Confirmation (§7)
│   ├── requires: accepted & announced papers
│   └── Creates proof -> uploads file -> notifies author -> author confirms/comments
│
└── Ongoing Administration (§8)
    └── Duplicate report review (background scan)
```

---

## §1: Conference Setup

### Create Conference

- **Actor:** Global Admin
- **Goal:** Establish a new conference.
- **Preconditions:** User has global admin or superuser role.
- **Steps:**
    1. Admin opens the home page and enters a conference name in the creation form.
    2. System creates and activates the conference.
- **Outcome:** Conference exists and is ready for further configuration (tracks, code
  pools, attendance types, invitations).

### Create Tracks and Code Pools

- **Actor:** Conference Chair
- **Goal:** Add tracks and assign paper code pools for unique paper identifiers.
- **Preconditions:** Conference exists and is active.
- **Steps:**
    1. Chair opens the conference admin settings page and navigates to the Tracks tab.
    2. Chair fills in a track display name, visibility, and submission settings, then
       saves.
    3. Chair navigates to the Code Pools tab, creates a pool with a name and prefix (
       e.g., `"CBPK-2"` produces codes `CBPK-2001`, `CBPK-2002`, ...).
    4. Back on the Tracks tab, chair assigns the code pool to one or more tracks.
- **Outcome:** Tracks exist with code pools; papers submitted to those tracks receive
  unique codes.

### Configure Attendance Types

- **Actor:** Conference Chair
- **Goal:** Define registration categories (e.g., Student, Professional, Virtual).
- **Preconditions:** Conference exists and is active.
- **Steps:**
    1. Chair opens the conference admin settings page and navigates to the Attendance
       Types tab.
    2. Chair enters a display name, selects whether this type is admin-only and whether
       it requires a paper, and saves.
- **Outcome:** Attendance type available for registration (see §6).

### Invite Committee Members and Reviewers

- **Actor:** Conference Chair or Secretary
- **Goal:** Send role invitations to users via email.
- **Preconditions:** Conference is active; no pending invitation exists for the same
  email.
- **Steps:**
    1. Admin opens the conference members page and creates an invitation with the
       invitee's email and role assignments (conference and/or track roles).
    2. Admin selects one or more pending invitations and clicks "Send Invitation
       Emails", which opens a modal to compose the email (subject, body with template
       variables for name, accept/reject URLs, etc.) and send it.
    3. Invitee receives the email and follows the link (see §2: Redeem Invitation).
- **Outcome:** Invitation created in `PENDING` state; email delivered with accept/reject
  links.

---

## §2: Account & Authentication

### Sign Up

- **Actor:** New user
- **Goal:** Create an account with a verified email.
- **Preconditions:** None.
- **Steps:**
    1. User opens the sign-up page and enters an email address, then clicks "Send Code".
    2. User receives a 6-digit code by email, enters it, and the field shows a verified
       checkmark.
    3. User fills in username, password, and profile fields (name, affiliation, region),
       then clicks "Create account".
    4. System creates the account and logs the user in automatically.
- **Outcome:** Active user account exists; user is redirected to the home page.

### Log In

- **Actor:** Existing user
- **Goal:** Authenticate and establish a session.
- **Preconditions:** User account exists and is active.
- **Steps:**
    1. User opens the login page, enters username and password, and clicks "Log in".
- **Outcome:** Authenticated session established; user is redirected to the home page.

### Password Reset

- **Actor:** User who forgot their password
- **Goal:** Reset password via email verification.
- **Preconditions:** User account exists.
- **Steps:**
    1. User clicks "Forgot password?" on the login page and enters their email address.
    2. System sends a reset link (success message shown regardless of whether the
       account exists, to prevent enumeration).
    3. User clicks the link in the email, enters a new password, and confirms it.
- **Outcome:** Password updated; user can log in with new credentials.

### Redeem Invitation

- **Actor:** Invited user
- **Goal:** Accept a conference invitation and receive assigned roles.
- **Preconditions:** Invitation is in `PENDING` or `REJECTED` state; conference is
  active.
- **Steps:**
    1. Invitee clicks the accept link in the invitation email, which opens the
       invitation page showing the conference name and assigned roles.
    2. If the invitee has no account, they click "Sign Up" (the sign-up form pre-fills
       name, affiliation, and email from the invitation).
    3. Once logged in, the invitee clicks "Accept Invitation".
    4. System creates role assignments and a conference profile for the user.
- **Outcome:** Invitation transitions to `ACCEPTED`; user receives all specified
  conference and track roles. Reviewers are redirected to set their review preferences
  (desired paper count, interested keywords); other roles are redirected to the
  conference.

### Reject Invitation

- **Actor:** Invited user
- **Goal:** Decline a conference invitation.
- **Preconditions:** Invitation is in `PENDING` state.
- **Steps:**
    1. Invitee clicks the reject link in the invitation email.
    2. System transitions the invitation to `REJECTED`.
- **Outcome:** Invitation is rejected. Admins can resend or update it; the invitee can
  still redeem it later (see Redeem Invitation above).

---

## §3: Paper Lifecycle

### Create Draft Paper

- **Actor:** Author
- **Goal:** Start a new paper submission in a track.
- **Preconditions:** Conference and track are active; track has a code pool configured.
- **Steps:**
    1. Author opens "My Papers" and clicks "New Paper".
    2. Author selects a track (immutable after creation), fills in the title, and
       optionally adds authors, abstract, and keywords.
    3. Author clicks "Save & Continue".
    4. System allocates a unique paper code from the track's code pool.
- **Outcome:** Draft paper exists with allocated code; author is redirected to the paper
  detail page.

### Edit Draft and Upload Submission

- **Actor:** Author
- **Goal:** Update paper metadata and upload the manuscript.
- **Preconditions:** Paper is in `DRAFT` state.
- **Steps:**
    1. Author opens the paper detail page and edits metadata (title, authors, abstract,
       contribution, keywords).
    2. Author uploads the manuscript file via the file upload area (drag-and-drop or
       file picker); a progress bar tracks the upload.
    3. Author clicks "Save Draft".
- **Outcome:** Paper metadata and submission file updated.

### Submit Paper for Review

- **Actor:** Author
- **Goal:** Transition paper from draft to submitted for review.
- **Preconditions:** Paper is in `DRAFT` state; the sidebar validation checklist shows
  all items green (title, abstract, contribution, keywords, authors with exactly one
  corresponding author, submission file).
- **Steps:**
    1. Author clicks "Submit for Review" in the sidebar (enabled only when all checks
       pass and the form is saved).
    2. A confirmation modal warns that the paper cannot be edited after submission.
    3. Author confirms; system validates completeness and transitions to `SUBMITTED`.
- **Outcome:** Paper is in `SUBMITTED` state; visible to admins and eligible for
  reviewer assignment. Author can unsubmit to return to `DRAFT`.

### Upload Final (Camera-Ready) Version

- **Actor:** Author
- **Goal:** Submit the camera-ready version of an accepted paper.
- **Preconditions:** Paper is `ACCEPTED` or `ACCEPTED_REVISION_NEEDED`; decision has
  been announced; final revision limit not exceeded.
- **Steps:**
    1. Author opens the paper detail page and clicks "Upload Final Version" in the
       sidebar.
    2. In the modal, author selects a source file (required) and an optional viewable
       file, then confirms.
    3. System validates files and checks remaining upload quota.
- **Outcome:** Final revision stored; remaining upload quota decremented.

### Withdraw Paper

- **Actor:** Author
- **Goal:** Withdraw paper from consideration.
- **Preconditions:** Paper is not already withdrawn.
- **Steps:**
    1. Author opens the paper detail page and clicks "Withdraw".
    2. System marks the paper as withdrawn.
- **Outcome:** Paper is withdrawn (terminal). It remains visible in statistics but
  cannot be edited, submitted, or decided upon.

---

## §4: Review Lifecycle

### Assign Reviewer

- **Actor:** Conference or Track Admin
- **Goal:** Create a review assignment for a paper.
- **Preconditions:** Paper is not in `DRAFT` state and not withdrawn; reviewer has an
  eligible role; no active review exists for this paper-reviewer pair.
- **Steps:**
    1. Admin opens the paper's "Manage Reviews" page, which shows a searchable table of
       candidate reviewers with their current/desired assignment counts and skill match
       scores.
    2. Admin clicks "Assign" next to the chosen reviewer.
    3. If paper is `SUBMITTED`, it transitions to `UNDER_REVIEW`.
- **Outcome:** Review created in `PENDING` state; reviewer sees it in their review list.

### Accept Assignment and Submit Review

- **Actor:** Reviewer
- **Goal:** Accept the assignment, draft, and submit a completed review.
- **Preconditions:** Review is in `PENDING` state.
- **Steps:**
    1. Reviewer opens "My Reviews", which groups reviews by state (Pending, In Progress,
       Submitted, Declined). Reviewer clicks "Accept" on a pending assignment.
    2. Reviewer opens the review detail page and fills in scores (six criteria rated
       1-5: originality, significance, technical quality, references, presentation,
       topic match), recommendation (1-5), and text fields (contribution summary,
       decision reason, optional comments and confidential remarks). Clicks "Save Draft"
       as needed.
    3. When all required fields are complete, reviewer clicks "Submit Review" and
       confirms in the modal.
- **Outcome:** Review transitions to `SUBMITTED` and becomes visible to admins for
  decision-making.

### Import External Review

- **Actor:** Conference or Track Admin
- **Goal:** Add a review from an external source (offline reviewer).
- **Preconditions:** Paper exists.
- **Steps:**
    1. Admin opens the paper's "Manage Reviews" page and clicks "Import External
       Review".
    2. In the modal, admin fills in an optional reviewer name, scores, and text fields,
       then clicks "Import".
- **Outcome:** Imported review is created directly in `SUBMITTED` state and appears
  alongside online reviews.

### Cancel or Return Review (Admin)

- **Actor:** Conference or Track Admin
- **Goal:** Cancel a review assignment or return a submitted review for revision.
- **Preconditions:** Review is in an active state (`PENDING`, `ACCEPTED`, or
  `SUBMITTED`).
- **Steps:**
    1. Admin opens the review detail page from the paper's "Manage Reviews" page.
    2. To cancel: admin clicks "Cancel Assignment", which transitions to `CANCELLED`.
    3. To return for revision: admin clicks "Unsubmit" on a submitted review, which
       transitions it back to `ACCEPTED` so the reviewer can revise and resubmit.
- **Outcome:** Cancelled reviews free the assignment slot. Unsubmitted reviews return to
  the reviewer's draft queue.

### Send Review Notifications

- **Actor:** Conference Admin
- **Goal:** Notify reviewers of pending and accepted assignments via email.
- **Preconditions:** Reviewers have pending or accepted reviews.
- **Steps:**
    1. Admin opens the "Notify Reviewers" page from the admin paper list.
    2. Admin selects reviewers, composes the email using template variables (reviewer
       name, pending/accepted counts, etc.), and optionally previews the rendered
       output.
    3. Admin clicks "Send"; system sends emails respecting rate limits and logs
       notification timestamps.
- **Outcome:** Reviewers receive notification emails; notification log updated.

---

## §5: Decisions & Announcements

### Make Decision

- **Actor:** Conference Chair
- **Goal:** Accept, reject, or request revision for a submitted paper.
- **Preconditions:** Paper is not in `DRAFT` state and not withdrawn.
- **Steps:**
    1. Chair opens the paper's decision page, which shows all submitted reviews with
       their scores expanded, admin comments, and the decision history.
    2. Chair selects a decision (`ACCEPTED`, `REJECTED`, or `ACCEPTED_REVISION_NEEDED`)
       from the sidebar dropdown, optionally adds an internal note, and clicks "Make
       Decision".
    3. System records the decision and updates the paper's status.
- **Outcome:** Paper has a decision, which remains hidden from authors until announced.

### Generate Acceptance Letter

- **Actor:** Conference Admin
- **Goal:** Create a PDF acceptance letter for an accepted paper.
- **Preconditions:** Paper is `ACCEPTED` or `ACCEPTED_REVISION_NEEDED`.
- **Steps:**
    1. Admin opens the paper detail page and clicks "Generate Letter" (or "Regenerate
       Letter" if one exists), which opens a modal.
    2. Admin enters a Typst template (context variables: conference, track, paper,
       authors) and optionally clicks "Preview" to open the rendered PDF in a new tab.
    3. Admin clicks "Generate"; system compiles the template to PDF and stores it.
- **Outcome:** Acceptance letter PDF stored; paper is now eligible for announcement.
  Authors can download the letter after announcement.

### Announce Decisions

- **Actor:** Conference Admin
- **Goal:** Reveal decisions to authors in bulk.
- **Preconditions:** Papers have decisions; accepted papers must have acceptance letters
  generated.
- **Steps:**
    1. Admin selects papers from the admin paper list (or opens a single paper detail)
       and clicks "Announce", which opens a confirmation modal.
    2. Admin confirms; system announces decisions on eligible papers and reports how
       many were announced vs. skipped.
- **Outcome:** Authors can now see their paper's true decision state, download their
  acceptance letter (if accepted), and view anonymized reviewer feedback.

---

## §6: Registration & Payments

### Register for Conference

- **Actor:** Author
- **Goal:** Submit a registration application.
- **Preconditions:** Conference has registration enabled; if attendance type requires a
  paper, paper must be in an announced accepted state (see §5).
- **Steps:**
    1. Author opens the registration page and selects an attendance type; if the type
       requires a paper, a paper dropdown appears.
    2. Author fills in profile data (receipt title, name, affiliation, region, email,
       phone, self-introduction) and clicks "Submit Registration".
    3. System generates a unique reference code for payment matching.
- **Outcome:** Registration created in `PENDING` state. Author sees the reference code
  and instructions to include it when making payment.

### Confirm Registration

- **Actor:** Conference Admin
- **Goal:** Approve pending registrations.
- **Preconditions:** Registrations exist in `PENDING` state.
- **Steps:**
    1. Admin opens the admin registration list, filters by state, and selects one or
       more pending registrations via checkboxes.
    2. Admin chooses "Confirm" from the bulk action dropdown and clicks "Apply".
    3. Alternatively, admin opens a single registration detail and changes the state
       dropdown to "Confirmed".
- **Outcome:** Selected registrations transition to `CONFIRMED`.

### Record Payment

- **Actor:** Conference Admin
- **Goal:** Record an offline payment received from an attendee.
- **Preconditions:** One or more registrations exist.
- **Steps:**
    1. Admin opens the "New Payment" page and fills in amount, currency, type (Payment
       or Refund), method (Credit Card, Wire Transfer, Other), and optional
       reference/note.
    2. Admin clicks "Add Item" to add line items, each linking a registration (
       searchable dropdown), description, and amount. A warning appears if item totals
       do not match the payment amount.
    3. Admin clicks "Create Payment".
- **Outcome:** Payment record created; linked to registrations via payment items.

### Generate Receipt

- **Actor:** Conference Admin
- **Goal:** Create a PDF receipt for a registration.
- **Preconditions:** Registration exists (not cancelled).
- **Steps:**
    1. Admin opens the registration detail page and clicks "Generate Receipt" (or
       "Regenerate Receipt") in the sidebar, which opens a modal.
    2. Admin enters a Typst template (context variables: conference, registration) and
       optionally clicks "Preview" to see the rendered PDF.
    3. Admin clicks "Generate"; system compiles the template to PDF and stores it.
    4. Attendee can later download the receipt via a public link.
- **Outcome:** Receipt PDF generated and available for download.

---

## §7: Proof Confirmation

Before finalizing proceedings, the committee edits accepted papers for formatting and
typos, then asks authors to review the edited version and confirm or leave feedback.

Proof records do not have a formal state enum. Status is derived from timestamps
(confirmed, commented, notified). These are not mutually exclusive; a proof can be both
confirmed and commented. Uploading a new file resets confirmation and comments.

### Create Proof Record

- **Actor:** Conference Admin
- **Goal:** Create a proof record for an accepted paper with a derived recipient.
- **Preconditions:** Paper is `ACCEPTED` or `ACCEPTED_REVISION_NEEDED`; decision has
  been announced; paper is not withdrawn or deleted.
- **Steps:**
    1. Admin creates a proof record for a paper, optionally overriding the recipient
       name and email.
    2. System derives the recipient from the first corresponding author, or falls back
       to the paper owner. Explicit overrides take precedence.
- **Outcome:** Proof record created (one per paper). No file attached yet.

### Upload Proof File

- **Actor:** Conference Admin
- **Goal:** Attach the edited PDF to a proof record.
- **Preconditions:** Proof record exists for the paper.
- **Steps:**
    1. Admin uploads a PDF file to the proof record.
    2. System validates the file. If replacing an existing file, confirmation and
       comments are reset.
- **Outcome:** Proof file stored; proof is ready for author notification.

### Send Proof Notifications

- **Actor:** Conference Admin
- **Goal:** Email authors with links to review their proofs.
- **Preconditions:** Proof records exist; proofs without files are skipped.
- **Steps:**
    1. Admin opens the "Proof Confirmation" page from the admin paper list.
    2. Admin selects one or more proofs via checkboxes and clicks "Send Notification".
    3. In the modal, admin composes the email template and optionally previews the
       rendered output.
    4. Admin clicks "Send"; system sends emails and records notification timestamps.
       Proofs without uploaded files are skipped.
- **Outcome:** Authors receive emails with token-based links (no login required) to
  their proof pages; notification timestamps updated.

### Confirm Proof

- **Actor:** Author (via token link)
- **Goal:** Approve the edited version for proceedings.
- **Preconditions:** Author has the proof URL (from notification email).
- **Steps:**
    1. Author opens the proof link, which shows the paper code, title, and instructions.
    2. Author downloads and reviews the proof PDF.
    3. Author clicks "Confirm Proof".
- **Outcome:** Proof is confirmed. Idempotent; confirming again is a no-op. Admin sees
  "Confirmed" status on the proof list.

### Comment on Proof

- **Actor:** Author (via token link)
- **Goal:** Report errors or request changes to the edited version.
- **Preconditions:** Author has the proof URL.
- **Steps:**
    1. Author opens the proof link and enters feedback in the comment textarea.
    2. Author clicks "Submit Comment".
- **Outcome:** Comment stored with timestamp. Admin sees "Commented" status on the proof
  list and can expand to read the comment. Communication for resolving comments happens
  offline (email, etc.).

---

## §8: Ongoing Administration

### Review Duplicate Report

- **Actor:** Conference Admin
- **Goal:** Review flagged duplicate paper submissions and record acknowledgments.
- **Preconditions:** A background scan has produced a successful `DuplicateReport`.
- **Steps:**
    1. Admin opens the "Duplicate Report" page from the admin paper list.
    2. Report shows matches by file hash (identical PDF) or title similarity, sorted
       with unacknowledged matches first by descending similarity score.
    3. Admin clicks the acknowledgment button on a match, which opens a modal showing
       both papers and an optional note field.
    4. Admin enters a note explaining the decision and clicks "Acknowledge".
- **Outcome:** Matches are acknowledged with notes; acknowledged matches sort below
  unacknowledged ones in future views.

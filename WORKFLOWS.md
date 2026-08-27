# Workflows

This document describes the system's major user-facing workflows (happy paths only).
Absence of a flow here does not mean the application lacks it: account management,
impersonation, admin conveniences (e.g. bulk actions, editing on a user's behalf), and
the scripted API workflows in the admin API guides are deliberately not described.

## Conventions

- **Actor roles:** Global Admin (superuser or global admin role), Conference
  Chair/Secretary (conference-level admins), Track Chair/Secretary (track-level admins),
  Reviewer, Author, User (any authenticated user).
- **State transitions** use arrow notation: `DRAFT -> SUBMITTED`.
- **Cross-references** link to other workflows with `(see §N: Name)`.
- **Altitude:** steps describe what the actor does and what the system does, not which
  page element they use; preconditions state the gate, not the validation rules behind
  it.

## State Machine Reference

### Paper

```text
DRAFT -> SUBMITTED -> UNDER_REVIEW -> ACCEPTED
                                   -> ACCEPTED_REVISION_NEEDED
                                   -> REJECTED
```

- `SUBMITTED -> DRAFT` (unsubmit, author only).
- `SUBMITTED` transitions to `UNDER_REVIEW` when the first reviewer is assigned.
- Decided states: `ACCEPTED`, `ACCEPTED_REVISION_NEEDED`, `REJECTED`. A decision can
  also be made directly from `SUBMITTED` (e.g. invited papers), and a decided paper can
  be decided again; each decision appends to the paper's decision history.
- Any state can become `Withdrawn` (terminal flag, not a formal state). Authors can
  instead delete a `DRAFT` or `SUBMITTED` paper (soft delete, also a terminal flag).
- Authors see `UNDER_REVIEW` until the decision is announced, even if a decision exists,
  and see `ACCEPTED_REVISION_NEEDED` as `ACCEPTED` after announcement.

### Review

```text
PENDING -> ACCEPTED -> SUBMITTED
PENDING -> DECLINED (terminal)
Any active state -> CANCELLED (terminal)
```

- Active states: `PENDING`, `ACCEPTED`, `SUBMITTED`.
- Admin can return a submitted review for revision (`SUBMITTED` back to `ACCEPTED`).
- Imported (offline) reviews are created directly in `SUBMITTED` with no reviewer; they
  cannot be returned for revision and do not move the paper to `UNDER_REVIEW`.

### Registration

```text
PENDING -> CONFIRMED
PENDING -> CANCELLED
```

- Registrants can only edit or cancel while `PENDING`; admins can set any state from
  any state.

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
│   ├── requires: tracks with code pools and submissions open, authenticated author
│   └── Author (or admin on their behalf) creates -> submits -> paper enters review
│
├── Review Lifecycle (§4)
│   ├── requires: submitted papers, assigned reviewers; no new assignments once
│   │             announced (§5)
│   └── Assign -> accept -> submit review
│
├── Decisions & Announcements (§5)
│   ├── requires: submitted papers (optionally with reviews)
│   └── Decide -> generate letter (accepted) -> announce
│
├── Registration & Payments (§6)
│   ├── requires: registration open, attendance types, announced/accepted paper (if
│   │             paper required)
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
    1. Admin creates the conference by name from the home page.
    2. System creates and activates the conference.
- **Outcome:** Conference exists and is ready for further configuration (tracks, code
  pools, attendance types, invitations).

### Create Tracks and Code Pools

- **Actor:** Conference Chair
- **Goal:** Add tracks and assign paper code pools for unique paper identifiers.
- **Preconditions:** Conference exists and is active.
- **Steps:**
    1. Chair creates a track in the conference settings, choosing its visibility. New
       tracks do not accept submissions yet.
    2. Chair creates a code pool with a name and prefix (e.g., `"CBPK-2"` produces codes
       `CBPK-2001`, `CBPK-2002`, ...) and assigns it to one or more tracks.
    3. Chair opens submissions on each track that should accept papers.
- **Outcome:** Tracks exist with code pools and accept submissions; papers submitted to
  those tracks receive unique codes.

### Configure Attendance Types

- **Actor:** Conference Chair
- **Goal:** Define registration categories (e.g., Student, Professional, Virtual) and
  open registration.
- **Preconditions:** Conference exists and is active.
- **Steps:**
    1. Chair defines an attendance type in the conference settings, choosing whether it
       is admin-only and whether it requires a paper.
    2. Chair enables registration for the conference (disabled by default).
- **Outcome:** Attendance type available for registration (see §6).

### Invite Committee Members and Reviewers

- **Actor:** Conference Chair or Secretary; Track Chair or Secretary for roles on their
  own tracks.
- **Goal:** Send role invitations to users via email.
- **Preconditions:** Conference is active; no unaccepted invitation exists for the same
  email (a rejected invitation also blocks a new one).
- **Steps:**
    1. Admin creates an invitation for the invitee's email with conference and/or track
       role assignments. Assignable roles follow the inviter's own role: chairs assign
       any role, secretaries assign Reviewer and Member only, track admins assign roles
       on their own tracks only.
    2. Conference admins send the invitation email (composed from a template with accept
       and reject links) to selected pending invitations; track admins share the accept
       link directly.
    3. Invitee follows the link (see §2: Redeem Invitation).
- **Outcome:** Invitation created in `PENDING` state; email delivered with accept/reject
  links.

---

## §2: Account & Authentication

### Sign Up

- **Actor:** New user
- **Goal:** Create an account with a verified email.
- **Preconditions:** None.
- **Steps:**
    1. User enters an email address on the sign-up page and verifies it with the code
       the system emails them.
    2. User fills in username, password, and profile details and creates the account.
    3. System creates the account and logs the user in.
- **Outcome:** Active user account exists; user is redirected to the home page.

### Log In

- **Actor:** Existing user
- **Goal:** Authenticate and establish a session.
- **Preconditions:** User account exists and is active.
- **Steps:**
    1. User signs in with username and password.
- **Outcome:** Authenticated session established; user is redirected to the home page.

### Password Reset

- **Actor:** User who forgot their password
- **Goal:** Reset password via email verification.
- **Preconditions:** User account exists and is active.
- **Steps:**
    1. User requests a reset from the login page with their email address.
    2. System emails a reset link. The same success message is shown whether or not an
       active account exists, to prevent enumeration.
    3. User sets a new password through the link.
- **Outcome:** Password updated; user can log in with new credentials.

### Redeem Invitation

- **Actor:** Invited user
- **Goal:** Accept a conference invitation and receive assigned roles.
- **Preconditions:** Invitation is in `PENDING` or `REJECTED` state; conference is
  active.
- **Steps:**
    1. Invitee opens the accept link from the invitation email, which shows the
       conference the invitation is for.
    2. An invitee without an account signs up from there; the sign-up form pre-fills
       name, affiliation, and email from the invitation, and the invitation is redeemed
       as part of account creation.
    3. An invitee with an account logs in and accepts the invitation.
    4. System creates role assignments and a conference profile for the user.
- **Outcome:** Invitation transitions to `ACCEPTED`; user receives all specified
  conference and track roles. Users granted any reviewing role (Chair, Secretary, or
  Reviewer, at conference or track level) are redirected to set their review
  preferences (desired paper count, interested keywords); Member-only invitees are
  redirected to the conference.

### Reject Invitation

- **Actor:** Invited user
- **Goal:** Decline a conference invitation.
- **Preconditions:** Invitation is in `PENDING` state; conference is active.
- **Steps:**
    1. Invitee opens the reject link from the invitation email.
    2. System transitions the invitation to `REJECTED`.
- **Outcome:** Invitation is rejected. Admins can resend or update it; the invitee can
  still redeem it later (see Redeem Invitation above).

---

## §3: Paper Lifecycle

### Create Draft Paper

- **Actor:** Author
- **Goal:** Start a new paper submission in a track.
- **Preconditions:** Conference and track are active; track has a code pool and accepts
  submissions.
- **Steps:**
    1. Author starts a new paper from the conference sidebar (offered only while some
       track accepts submissions).
    2. Author selects a track (immutable after creation), fills in the paper's
       metadata, and saves.
    3. System allocates a unique paper code from the track's code pool.
- **Outcome:** Draft paper exists with allocated code; author is redirected to the paper
  detail page.

### Edit Draft and Upload Submission

- **Actor:** Author
- **Goal:** Update paper metadata and upload the manuscript.
- **Preconditions:** Paper is in `DRAFT` state.
- **Steps:**
    1. Author edits the paper's metadata on the paper detail page and saves.
    2. Author uploads the manuscript file; the upload starts on file selection and
       shows progress.
- **Outcome:** Paper metadata and submission file updated.

### Submit Paper for Review

- **Actor:** Author
- **Goal:** Transition paper from draft to submitted for review.
- **Preconditions:** Paper is in `DRAFT` state and passes submission validation; the
  paper page lists anything still missing.
- **Steps:**
    1. Author submits the paper from the detail page (offered only when the paper is
       complete and saved) and confirms the warning that it cannot be edited after
       submission.
    2. System validates completeness and transitions the paper to `SUBMITTED`.
- **Outcome:** Paper is in `SUBMITTED` state; visible to admins and eligible for
  reviewer assignment. The owner receives a submission confirmation email. Author can
  unsubmit to return to `DRAFT`.

### Upload Final (Camera-Ready) Version

- **Actor:** Author
- **Goal:** Submit the camera-ready version of an accepted paper.
- **Preconditions:** Paper is `ACCEPTED` or `ACCEPTED_REVISION_NEEDED`; decision has
  been announced; final revision limit not exceeded.
- **Steps:**
    1. Author uploads a final version from the paper detail page: a source file
       (required) and an optional viewable file.
    2. System validates the files and checks the remaining upload quota.
- **Outcome:** Final revision stored; remaining upload quota decremented.

### Withdraw Paper

- **Actor:** Author
- **Goal:** Withdraw paper from consideration.
- **Preconditions:** Paper is not already withdrawn and, as seen by the author, is
  `UNDER_REVIEW` or announced as accepted. `DRAFT` and `SUBMITTED` papers are deleted
  instead (see State Machine Reference).
- **Steps:**
    1. Author withdraws the paper from the paper detail page.
    2. System marks the paper as withdrawn.
- **Outcome:** Paper is withdrawn (terminal). It remains visible in statistics but
  cannot be edited, submitted, or decided upon.

---

## §4: Review Lifecycle

### Assign Reviewer

- **Actor:** Conference or Track Admin
- **Goal:** Create a review assignment for a paper.
- **Preconditions:** Paper is not in `DRAFT` state, not withdrawn, and its decision (if
  any) is not yet announced; reviewer has an eligible role; no active review exists for
  this paper-reviewer pair.
- **Steps:**
    1. Admin picks a reviewer for the paper from the candidate list, which shows each
       reviewer's current and desired assignment counts and skill match score.
    2. If the paper is `SUBMITTED`, it transitions to `UNDER_REVIEW`.
- **Outcome:** Review created in `PENDING` state; reviewer sees it in their review list.

### Accept Assignment and Submit Review

- **Actor:** Reviewer
- **Goal:** Accept the assignment, draft, and submit a completed review.
- **Preconditions:** Review is in `PENDING` state.
- **Steps:**
    1. Reviewer accepts the pending assignment from their review list.
    2. Reviewer fills in the review: scores on the review criteria, a recommendation,
       and free-text sections (some confidential to admins), saving drafts as needed.
    3. When all required fields are complete, reviewer submits the review and confirms.
- **Outcome:** Review transitions to `SUBMITTED` and becomes visible to admins for
  decision-making.

### Import External Review

- **Actor:** Conference Admin
- **Goal:** Add a review from an external source (offline reviewer).
- **Preconditions:** Paper is not in `DRAFT` state.
- **Steps:**
    1. Admin imports a review for the paper with an optional reviewer name, scores, and
       text fields. Importing again with the same reviewer name overwrites that review;
       an empty name always creates a new one.
- **Outcome:** Imported review is created directly in `SUBMITTED` state and appears
  alongside online reviews.

### Cancel or Return Review (Admin)

- **Actor:** Conference or Track Admin (track admins only for track-level assignments
  on their own tracks; conference-level assignments are not visible to them)
- **Goal:** Cancel a review assignment or return a submitted review for revision.
- **Preconditions:** Review is in an active state (`PENDING`, `ACCEPTED`, or
  `SUBMITTED`); for track admins, the paper's decision is not yet announced.
- **Steps:**
    1. To cancel: admin cancels the assignment, which transitions the review to
       `CANCELLED`.
    2. To return for revision: admin unsubmits a submitted review, which transitions it
       back to `ACCEPTED` so the reviewer can revise and resubmit. Imported reviews
       cannot be unsubmitted.
- **Outcome:** Cancelled reviews free the assignment slot. Unsubmitted reviews return to
  the reviewer's draft queue.

### Send Review Notifications

- **Actor:** Conference Admin
- **Goal:** Notify reviewers of pending and accepted assignments via email.
- **Preconditions:** Reviewers have pending or accepted reviews.
- **Steps:**
    1. Admin selects reviewers and composes the email from a template (variables such
       as reviewer name and pending/accepted counts), optionally previewing the rendered
       output.
    2. Admin sends; system delivers emails respecting rate limits and logs notification
       timestamps.
- **Outcome:** Reviewers receive notification emails; notification log updated.

---

## §5: Decisions & Announcements

### Make Decision

- **Actor:** Conference Chair
- **Goal:** Accept, reject, or request revision for a submitted paper.
- **Preconditions:** Paper is not in `DRAFT` state and not withdrawn.
- **Steps:**
    1. Chair reviews the paper's submitted reviews (with scores), admin comments, and
       decision history on the decision page.
    2. Chair records a decision (`ACCEPTED`, `REJECTED`, or `ACCEPTED_REVISION_NEEDED`)
       with an optional internal note.
    3. System records the decision and updates the paper's state.
- **Outcome:** Paper has a decision, hidden from authors until announced. A changed
  decision on an already announced paper is visible to authors immediately.

### Generate Acceptance Letter

- **Actor:** Conference Admin
- **Goal:** Create a PDF acceptance letter for an accepted paper.
- **Preconditions:** Paper is `ACCEPTED` or `ACCEPTED_REVISION_NEEDED`.
- **Steps:**
    1. Admin generates (or regenerates) the letter for the paper, or for several papers
       at once from the paper list, from a Typst template (context variables:
       conference, track, paper, authors), optionally previewing the rendered PDF.
    2. System compiles the template to PDF and stores it.
- **Outcome:** Acceptance letter PDF stored; paper is now eligible for announcement. The
  letter is not visible to authors in the application; it reaches them as an attachment
  when an admin emails it through the email-sending API (see the admin API guides).

### Announce Decisions

- **Actor:** Conference Admin
- **Goal:** Reveal decisions to authors in bulk.
- **Preconditions:** Papers have decisions; accepted papers must have acceptance letters
  generated.
- **Steps:**
    1. Admin announces one paper or a selection from the paper list and confirms.
    2. System announces decisions on eligible papers and reports how many were announced
       and how many skipped.
- **Outcome:** Authors see their paper's decision state (`ACCEPTED_REVISION_NEEDED`
  shown as `ACCEPTED`), and authors of accepted papers can view anonymized feedback
  (reviewer texts and admin comments).

---

## §6: Registration & Payments

### Register for Conference

- **Actor:** User
- **Goal:** Submit a registration application.
- **Preconditions:** Conference has registration enabled; if the attendance type
  requires a paper, the paper must be in an announced accepted state (see §5).
- **Steps:**
    1. User selects an attendance type (and a paper, if the type requires one) on the
       registration page.
    2. User fills in profile and receipt details and submits.
    3. System generates a unique reference code for payment matching.
- **Outcome:** Registration created in `PENDING` state. The registrant sees the
  reference code and instructions to include it when paying, and can edit or cancel the
  registration while it stays `PENDING`.

### Confirm Registration

- **Actor:** Conference Admin
- **Goal:** Approve pending registrations.
- **Preconditions:** Registrations exist in `PENDING` state.
- **Steps:**
    1. Admin confirms a selection of pending registrations from the registration list,
       or sets the state on a single registration's detail page (admins may set any
       state there).
- **Outcome:** Selected registrations transition to `CONFIRMED`.

### Record Payment

- **Actor:** Conference Admin
- **Goal:** Record an offline payment received from an attendee.
- **Preconditions:** One or more registrations exist.
- **Steps:**
    1. Admin creates a payment or refund with its amount, currency, and method, plus an
       optional reference and note.
    2. Admin adds line items, each linking a registration with a description and
       amount; the system warns when item totals do not match the payment amount.
- **Outcome:** Payment record created; linked to registrations via payment items.

### Generate Receipt

- **Actor:** Conference Admin
- **Goal:** Create a PDF receipt for a registration.
- **Preconditions:** Registration exists (not cancelled).
- **Steps:**
    1. Admin generates (or regenerates) the receipt for the registration, or for a
       selection from the registration list, from a Typst template (context variables:
       conference, registration), optionally previewing the rendered PDF.
    2. System compiles the template to PDF and stores it.
- **Outcome:** Receipt PDF stored. The receipt is not visible to the registrant in the
  application; it reaches them as an attachment when an admin emails it through the
  email-sending API (see the admin API guides), or via the link an admin shares.

---

## §7: Proof Confirmation

Before finalizing proceedings, the committee edits accepted papers for formatting and
typos, then asks authors to review the edited version and confirm or leave feedback.

Proof records do not have a formal state enum. Status is derived from timestamps
(confirmed, commented, notified). These are not mutually exclusive; a proof can be both
confirmed and commented. Uploading a new file resets confirmation and comments.

### Create Proof Record

- **Actor:** Conference Admin, through the API (no frontend page)
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

- **Actor:** Conference Admin, through the API (no frontend page)
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
    1. Admin selects proofs on the proof list and composes the notification email from
       a template, optionally previewing the rendered output.
    2. Admin sends; system delivers emails and records notification timestamps,
       skipping proofs without uploaded files.
- **Outcome:** Authors receive emails with token-based links (no login required) to
  their proof pages; notification timestamps updated.

### Confirm Proof

- **Actor:** Author (via token link)
- **Goal:** Approve the edited version for proceedings.
- **Preconditions:** Author has the proof URL (from notification email).
- **Steps:**
    1. Author opens the proof link, which shows the paper code, title, and instructions,
       and downloads the proof PDF.
    2. Author confirms the proof.
- **Outcome:** Proof is confirmed. Idempotent; confirming again is a no-op. Admin sees
  "Confirmed" status on the proof list.

### Comment on Proof

- **Actor:** Author (via token link)
- **Goal:** Report errors or request changes to the edited version.
- **Preconditions:** Author has the proof URL.
- **Steps:**
    1. Author submits feedback as a comment on the proof page.
- **Outcome:** Comment stored with timestamp. Admin sees "Commented" status on the proof
  list and can read the comment there. Communication for resolving comments happens
  offline (email, etc.).

---

## §8: Ongoing Administration

### Review Duplicate Report

- **Actor:** Conference Admin
- **Goal:** Review flagged duplicate paper submissions and record acknowledgments.
- **Preconditions:** A background scan has produced a successful `DuplicateReport`.
- **Steps:**
    1. Admin reviews the conference's duplicate report. The scan is global, so a match
       may pair a paper with one from another conference, shown with reduced detail
       depending on the admin's access to that conference. Matches are found by file
       hash (identical PDF) or title similarity and sorted with unacknowledged matches
       first by descending similarity score.
    2. Admin acknowledges a match with a note explaining the decision; an
       acknowledgment can later be updated or removed.
- **Outcome:** Matches are acknowledged with notes; acknowledged matches sort below
  unacknowledged ones in future views.

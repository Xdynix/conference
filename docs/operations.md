# Operations Runbook

Procedures for the running deployment. Read it when a log line or a Django admin page
needs an operator's action. Deploying, updating, and backups are in `docker/AGENTS.md`.

## Failed or Stuck Mail

Outgoing mail is queued in the database and delivered by the scheduler process. A
message that keeps failing is retried on a fixed interval, then marked failed; the
retry count and interval sit under `POST_OFFICE` in `app/settings.py`. The scheduler
logs a warning while any message awaits a retry and an error while any sits failed.
Rows are deleted after the retention period in `cleanup_mail` (`app/infra/jobs.py`)
regardless of status, so a failed message nobody acts on vanishes with its error.

Act as a superuser in the Django admin, under Post Office > Emails:

- Status `requeued` means the message is waiting for its next automatic attempt; the
  Logs inline shows each failure's exception. If the cause is on our side, such as bad
  relay credentials, fix it and the retries pick the message up.
- Status `failed` means the retries are used up. The Requeue action grants one more
  attempt, not a fresh retry cycle, so fix the cause first.
- Delete the row when the address itself is bad; retrying cannot help, and the error
  log repeats until the row is gone.
- Never use the per-message Resend button: it sends synchronously from the web process.
- Do not run `send_queued_mail` by hand beside the scheduler; both would send the same
  batch.
- Files under `DATA_DIR/post-office` that no `Attachment` row references were left by
  an enqueue that rolled back after writing them. Nothing reclaims them; delete them by
  hand if the store grows.

# Deployment Guidelines

Reference for modifying Docker, nginx, process management, or production settings.

## Deployment Files

<!-- markdownlint-disable MD013 -->

| File                             | Purpose                                                                                                                                |
|----------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `Dockerfile`                     | App image: installs deps, collects static, sets healthcheck and entrypoint.                                                            |
| `docker-compose.yml`             | Core services (`app`, `nginx`) and optional backup sidecars (`litestream`, `rclone`) gated behind the `backup` Compose profile.        |
| `docker/entrypoint.sh`           | Runs migrations before starting the CMD process.                                                                                       |
| `docker/supervisord.conf`        | Process manager config: app server (granian) and background workers.                                                                   |
| `docker/nginx.conf.template`     | Sidecar nginx: strips subpath, serves media via X-Accel-Redirect, proxies to app. Uses `envsubst` variables (`$APP_PORT`, `$SUBPATH`). |
| `docker/litestream.yml`          | Litestream config for continuous SQLite replication to WebDAV. Uses env var placeholders expanded at runtime.                          |
| `docker/10-normalize-subpath.sh` | Nginx entrypoint hook: strips trailing slash from `$SUBPATH` before `envsubst` runs. Mounted into `/docker-entrypoint.d/`.             |

<!-- markdownlint-enable MD013 -->

## First Deployment Checklist

1. Create `.env` from the project's environment variable documentation and fill in all
   secrets and site-specific values (see
   [Environment Variable Split](#environment-variable-split) for what belongs in `.env`
   vs. compose `environment`).
2. Create the external Docker network that nginx-proxy expects:
   `docker network create nginx-proxy`.
3. Create the host data directory (including the `media` subdirectory) and set ownership
   to the UID defined by `APP_UID` in the Dockerfile (see the compose file header
   comment for an example command). The `media` subdirectory must exist before the first
   start because the nginx sidecar bind-mounts it directly.
4. Verify the host-level nginx-proxy `client_max_body_size` is at least as large as the
   sidecar's value in `nginx.conf.template`. A smaller value on the outer proxy silently
   rejects uploads before they reach this stack.
5. **(Optional) Enable backups:** Set `COMPOSE_PROFILES=backup` in `.env`, fill in the
   `BACKUP_WEBDAV_*` credentials, and verify the WebDAV server is reachable from the
   host.
6. Build and start the stack: `docker compose up -d --build`.
7. Verify healthchecks: `docker compose ps` should show `app` and `nginx` as healthy
   (plus `litestream` and `rclone` if backups are enabled). The app healthcheck has a
   start period (see `HEALTHCHECK` in the Dockerfile), so allow time for it to become
   healthy after initial startup.

## Updating

1. Pull latest code and rebuild: `docker compose up -d --build`. The entrypoint runs
   `migrate --noinput` automatically on every start.
2. Verify healthchecks: `docker compose ps` (both services healthy).

## Coupling Rules

These are the invariants that must hold across files. Breaking one side without updating
the other will cause silent failures.

### Subpath Prefix

The external URL prefix (e.g., `/app`) must be consistent across three layers:

- `VIRTUAL_PATH` in compose `.env` (consumed by the nginx sidecar's `location` block).
- `FORCE_SCRIPT_NAME` in Django settings (derived from `VIRTUAL_PATH` via compose
  `environment`). Controls `reverse()`, `STATIC_URL`, `MEDIA_URL`, cookie paths.
- The sidecar's `proxy_pass http://app/` trailing slash strips the prefix, so granian
  always sees root-relative URLs.

Changing the prefix only requires updating `VIRTUAL_PATH` in `.env`. The compose
`environment` block and nginx template derive from it automatically.

### Media Serving (X-Accel-Redirect)

Three values must agree:

1. `FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX` in compose `environment` (what Django sends in
   the `X-Accel-Redirect` header).
2. The `location /internal-media/` block in `nginx.conf.template` (what nginx
   intercepts).
3. The `alias` directive in that location must point to the media volume mount path in
   the nginx container.

If you rename the internal location, update both the compose env var and the nginx
template.

### Shutdown Timing Chain

Three timeout values must satisfy a strict ordering:

<!-- markdownlint-disable MD013 -->

```text
granian --workers-kill-timeout  <  supervisord stopwaitsecs (app program)  <  docker stop_grace_period
```

<!-- markdownlint-enable MD013 -->

Each layer must finish before the next force-kills it. These live in `supervisord.conf`
(granian command args and `stopwaitsecs`), and `docker-compose.yml`
(`stop_grace_period`).

### Upstream Hostname

The nginx `upstream` block in `nginx.conf.template` uses `app` as the server hostname.
This must match the compose service name for the application container.

### Healthchecks

Two independent healthchecks exist:

- **App container** (`Dockerfile` `HEALTHCHECK`): hits granian directly on `localhost`.
  Because this bypasses the sidecar, `ALLOWED_HOSTS` in the compose `environment` block
  must include `localhost`, and the URL path must match an actual Django endpoint. No
  subpath prefix (granian always sees root-relative URLs).
- **Nginx container** (`docker-compose.yml` healthcheck): hits `/_ping`, which is
  handled by a local `location` block in `nginx.conf.template` (returns 200, not proxied
  to the app). If you rename or remove this location, the nginx healthcheck breaks.

### Backup Data Paths

The Litestream config (`docker/litestream.yml`) DB path must match `DATA_DIR` + the
database filename used by Django settings. Currently `/data/db.sqlite3`.

The rclone volume mount (`/media:ro`) must point at the media subdirectory inside
`HOST_DATA_DIR`. Currently `${HOST_DATA_DIR:-./.data}/media`.

If the data directory layout or database filename changes, update both the Litestream
config and the rclone volume mount accordingly.

## Environment Variable Split

### Compose `environment` Block (derived / topology-coupled)

Variables here are derived from infrastructure topology or must match hardcoded values
in the sidecar nginx config. They are not secrets. See `docker-compose.yml` for the
current set and the comments explaining each.

### `.env` File (secrets and user-configurable settings)

Application secrets (`SECRET_KEY`), database path overrides, email credentials,
Cloudflare Turnstile keys, branding, and site name. Loaded by Django's `decouple`
library. Never put these in the compose file or Dockerfile.

### Compose-level variables (in `.env`, consumed by compose itself)

`VIRTUAL_HOST`, `VIRTUAL_PATH`, `HOST_DATA_DIR`. These appear in compose interpolation
(`${VAR}`) and are not passed to Django directly.

## Constraints

### Reverse Proxy Count

`REVERSE_PROXY_COUNT` controls how `django-ipware` validates `X-Forwarded-For`. It uses
strict matching: `len(ips) - 1 == proxy_count`. A wrong count silently returns the wrong
client IP. Set in compose `environment` with a default of 1; can be overridden via
`.env`.

- 0 = direct connection (all proxy headers ignored). This is the Django settings
  default.
- 1 = sidecar nginx only (compose default).
- 2 = sidecar + an additional upstream proxy (e.g., Cloudflare).

When `REVERSE_PROXY_COUNT > 0`, Django automatically trusts `X-Forwarded-Proto: https`
(via `SECURE_PROXY_SSL_HEADER` in `app/settings.py`).

Related settings in `app/settings.py` (configured via `.env`):

- `CSRF_TRUSTED_ORIGINS`: comma-separated list of trusted origins (scheme + host + port)
  for CSRF validation. Required when the external origin includes a non-standard port or
  otherwise differs from what Django reconstructs via the `Host` header (e.g.,
  `https://example.com:8443`). Without this, Django's CSRF middleware rejects POST
  requests with "Origin checking failed".
- `REVERSE_PROXY_IP_HEADERS`: custom header order for IP resolution (e.g.,
  `CF-Connecting-IP` for Cloudflare).
- `REVERSE_PROXY_REQUEST_ID_HEADER`: adopts an upstream request ID header instead of
  generating one.

### Data Directory Ownership

The host data directory must be owned by the UID defined in `Dockerfile` ARG `APP_UID`
(the container's non-root user). The container will fail to write the database or media
files otherwise.

### SQLite Locality

The database file must reside on a local filesystem. Network filesystems (NFS, CIFS)
break SQLite's locking and cause data corruption.

### Supervisord Process Ordering

Programs start in ascending `priority` order. The app server should have the lowest
priority number so it starts first and passes healthchecks before workers begin. The
`exit-on-fatal` event listener causes the container to exit if any program enters FATAL
state, preventing silent degraded operation.

### Static Files

Collected at Docker build time (`collectstatic` in the Dockerfile). Served by the
`servestatic` middleware inside granian, not by nginx.

### Resource Limits

The container memory limit (`deploy.resources.limits.memory` in `docker-compose.yml`) is
the ceiling. Granian's `--workers-max-rss` in `supervisord.conf` is the per-worker
recycling threshold. The total budget must fit: (workers x max-rss) + background
workers + overhead < container limit. Exceeding the container limit causes OOM kills.

### Upload Size Limit

The maximum request body size is set via `client_max_body_size` in
`nginx.conf.template`. Each proxy in the chain enforces its own limit independently; the
host-level nginx-proxy must allow at least as much as the sidecar, otherwise it rejects
the request before it reaches this stack.

### Dependency Installation

The Dockerfile installs only production dependencies (
`--no-install-project --no-default-groups --group prod`). Ensure any new runtime
dependency is either ungrouped (default) or in the `prod` group.

The `uv sync` step runs as root before the `USER` directive. This is intentional: the
BuildKit cache mount defaults to `root:root`, and the resulting `.venv` is read-only at
runtime (`UV_COMPILE_BYTECODE` pre-compiles bytecode during install). Do not move `USER`
before the dependency installation step.

### Backup Sidecars

Both backup containers run as `${APP_UID:-900}` to match data directory ownership.
Litestream needs read-write access (WAL checkpointing); rclone only needs read access.
If `APP_UID` changes, update both sidecar `user` directives.

The rclone entrypoint uses `$$` escaping to prevent Docker Compose from interpolating
shell variables. It also runs `rclone obscure` at startup to convert the plaintext
password into the obscured format rclone requires. Edits to the entrypoint script must
preserve both mechanisms.

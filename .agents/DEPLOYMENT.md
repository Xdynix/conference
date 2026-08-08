# Deployment Guidelines

Reference for modifying Docker, nginx, process management, or production settings.

## Deployment Files

<!-- markdownlint-disable MD013 -->

| File                                | Purpose                                                                                                                                                                                            |
|-------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `Dockerfile`                        | App image: installs deps, collects static, sets healthcheck and entrypoint.                                                                                                                        |
| `docker-compose.yml`                | Core services (`app`, `nginx`) and optional backup sidecars (`litestream`, `rclone`) gated behind the `backup` Compose profile.                                                                    |
| `docker/entrypoint.sh`              | Runs migrations before starting the CMD process.                                                                                                                                                   |
| `docker/supervisord.conf`           | Process manager config: app server (granian) and background workers.                                                                                                                               |
| `docker/nginx.conf.template`        | Sidecar nginx: strips subpath, serves media via X-Accel-Redirect, proxies to app. Uses `envsubst` variables (`$APP_PORT`, `$SUBPATH`).                                                             |
| `docker/litestream.yml`             | Litestream config for continuous SQLite replication to Cloudflare R2. Uses env var placeholders expanded at runtime.                                                                               |
| `docker/10-normalize-subpath.envsh` | Nginx entrypoint hook: strips trailing slash from `$SUBPATH` before `envsubst` runs. Mounted into `/docker-entrypoint.d/`.                                                                         |
| `docker/11-write-real-ip-conf.sh`   | Nginx entrypoint hook: generates the sidecar's trust boundary from `$REAL_IP_FROM`, deciding whose client address and scheme it believes. Required; the template references a variable it defines. |

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
5. **(Optional) Enable backups:** Set `COMPOSE_PROFILES=backup` in `.env`, create the R2
   bucket and an API token scoped to object read/write, then fill in the `BACKUP_S3_*`
   values. Neither sidecar creates the bucket, so it must exist before first start. Add
   the bucket lifecycle rules described in [Backup Retention](#backup-retention); they
   are created by hand and are not provisioned by this stack.
6. **(Optional) Typst assets:** Place asset files (logos, organization chop images) into
   `${HOST_DATA_DIR}/assets/` on the host. This directory is read at runtime from
   `DATA_DIR/assets/` inside the container. Receipts will generate without the seal if
   it is absent.
7. Build and start the stack: `docker compose up -d --build`.
8. Verify startup: `docker compose ps` should show `app` and `nginx` as healthy. The app
   healthcheck has a start period (see `HEALTHCHECK` in the Dockerfile), so allow time
   for it to become healthy after initial startup. The `litestream` and `rclone`
   sidecars define no healthcheck and report only `Up` regardless of whether replication
   is working, so confirm those from their container logs instead.

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

### Nginx Entrypoint Hooks

The nginx image runs `/docker-entrypoint.d/*` in `sort -V` order before starting, and
both the extension and the file mode change the outcome. Getting either wrong skips the
hook without failing the container.

- A hook that sets environment variables for later hooks must be named `*.envsh`, which
  the entrypoint sources. A `*.sh` file runs in a child shell, losing any `export`, so
  that form suits hooks which only write files.
- Either kind must be executable. These are bind-mounted, so the mode comes from the
  file in this repository and has to be committed as `100755`.
- Anything that feeds `envsubst` must sort before `20-envsubst-on-templates.sh`.
- Unmounting `11-write-real-ip-conf.sh` is the exception to the silent-skip rule: the
  template uses `$forwarded_proto`, so nginx exits on an unknown variable instead.

Confirm with `docker compose logs nginx`, which reports `Sourcing`, `Launching`, or
`Ignoring ..., not executable` for each hook.

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
`HOST_DATA_DIR`. Currently `${HOST_DATA_DIR:-./var}/media`.

If the data directory layout or database filename changes, update both the Litestream
config and the rclone volume mount accordingly.

On the destination side, the sidecars write to the same R2 bucket under three prefixes.
Litestream owns `db/` (the `path` key in `docker/litestream.yml`), rclone mirrors the
media directory into `media/`, and rclone's `--backup-dir` moves overwritten or deleted
files into a dated folder under `media-trash/`. Without that backup directory a plain
`rclone sync` would propagate local deletions to the only remote copy.

### Backup Retention

Retention is split between Litestream and R2, and the two must be configured to agree.

`snapshot.retention` in `docker/litestream.yml` is what actually prunes database
history. R2 bucket lifecycle rules are a backstop only, because R2 can acknowledge a
delete request without performing it, leaving objects Litestream believes it removed.

The bucket requires the lifecycle rules below. Create them by hand in the R2 dashboard
under the bucket's Settings tab; nothing in this stack provisions them.

<!-- markdownlint-disable MD013 -->

| Prefix         | Action         | Age                           | Purpose                                                |
|----------------|----------------|-------------------------------|--------------------------------------------------------|
| `db/`          | Delete objects | At least `snapshot.retention` | Backstop for Litestream snapshot retention.            |
| `media-trash/` | Delete objects | Match the `db/` rule          | Ages out files rclone moved aside instead of deleting. |

<!-- markdownlint-enable MD013 -->

Keep the `db/` rule at or above `snapshot.retention` in `docker/litestream.yml`. A
shorter rule would delete history Litestream still considers live, and if replication
has silently stopped it would eventually remove the last remaining snapshot.

Never create a lifecycle rule on the `media/` prefix. That prefix holds the only copy of
current media files rather than a history, so an age-based rule would delete backups of
files that simply have not changed recently.

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

### App-Side Proxy Trust

Forwarding headers are ignored until `TRUSTED_PROXY` is set, because any client can send
them. Until then the client IP comes from the socket peer and `X-Forwarded-Proto` is not
believed, which is what a development server needs: it holds its own certificate, so the
connection scheme is already accurate.

Compose hardcodes `TRUSTED_PROXY: "true"` for the app, since the app publishes no ports
and is reachable only through the sidecar. That holds in every topology, so it is not a
per-deployment choice.

When it is set, both the scheme and the client IP come from headers the sidecar wrote,
so they are only as good as the trust boundary below.

`REVERSE_PROXY_COUNT` is an escape hatch and should stay at its default of `0`. It
counts hops that **append** to `X-Forwarded-For`, and the sidecar overwrites instead,
so nothing appends. Raise it only after editing the template back to appending, and
note that both failure directions are silent: too low returns a proxy address as the
client, too high resolves `client_ip` to `None`.

Related settings in `app/settings.py` (configured via `.env`):

- `CSRF_TRUSTED_ORIGINS`: comma-separated list of trusted origins (scheme + host + port)
  for CSRF validation. Required when the external origin includes a non-standard port or
  otherwise differs from what Django reconstructs via the `Host` header (e.g.,
  `https://example.com:8443`). Without this, Django's CSRF middleware rejects POST
  requests with "Origin checking failed".
- `REVERSE_PROXY_IP_HEADERS`: overrides which headers are tried, and in what order.
  Leave unset while the sidecar is in the chain, since it normalizes into
  `X-Forwarded-For` anyway. Ignored entirely when `TRUSTED_PROXY` is off.
- `REVERSE_PROXY_REQUEST_ID_HEADER`: adopts an upstream request ID header instead of
  generating one. Also gated on `TRUSTED_PROXY`.

### Sidecar Trust Boundary

The sidecar is where client-supplied forwarding headers stop. It overwrites
`X-Forwarded-For` with a single address instead of appending, and replaces
`X-Forwarded-Proto` unless a trusted peer supplied it, so nothing a client sends reaches
the app. `docker/11-write-real-ip-conf.sh` generates both rules from one setting.

`REAL_IP_FROM` takes a comma-separated list of addresses or CIDRs to trust, and defaults
to empty, meaning trust nothing. `REAL_IP_HEADER` names the header to read from a
trusted peer and defaults to `X-Real-IP`. Prefer single-valued headers, since
`X-Forwarded-For` additionally depends on `real_ip_recursive`, which this stack does not
expose.

`REAL_IP_FROM` therefore decides three things at once: the address in the sidecar's own
access log, the client IP the app resolves, and whether `X-Forwarded-Proto` is believed.
Leaving it empty behind a proxy is not merely a logging defect. The app then records
the proxy's address and treats every request as plain HTTP, breaking CSRF origin checks
on an HTTPS site. It fails closed rather than believing a forged value, but it fails.

The sidecar only ever sees its immediate upstream, so configure it from that one hop
rather than from the whole chain.

| Immediate upstream              | `REAL_IP_FROM`           | `REAL_IP_HEADER`   |
|---------------------------------|--------------------------|--------------------|
| Nothing; the port is published  | *(empty)*                | *(unused)*         |
| Cloudflare                      | Cloudflare's ranges      | `CF-Connecting-IP` |
| `nginx-proxy`, configured below | nginx-proxy network CIDR | `X-Real-IP`        |

Cloudflare behind `nginx-proxy` therefore gets no row of its own: by then `nginx-proxy`
has already resolved the client into `$remote_addr`.

That last row holds only if `nginx-proxy` is configured two ways, neither a default.

`TRUST_DOWNSTREAM_PROXY=false` is wanted, though not for the client IP: `nginx-proxy`
sets `X-Real-IP` from its own `$remote_addr` unconditionally, and the sidecar overwrites
`X-Forwarded-For` regardless of what arrives. What the setting still governs is
`X-Forwarded-Proto`. At its default of `true`, `nginx-proxy` passes a client's own value
through, and the sidecar believes it because `nginx-proxy` is a trusted peer, letting a
client assert `https` over a plaintext origin leg. With `false` it sends `$scheme`.

Whether that `$remote_addr` is the real client depends on `nginx-proxy` resolving it,
which for Cloudflare means its own `set_real_ip_from` list of Cloudflare's ranges plus
`real_ip_header CF-Connecting-IP`. `nginx-proxy` ships neither, so that config has to be
supplied to it. Without it `$remote_addr` is a Cloudflare edge address, and every layer
below records that as the client. Such a list is maintained by hand, so it can also go
stale against Cloudflare's published ranges with no symptom.

Trusting a whole Docker network grants that trust to every container on it, any of which
could then set the header. Narrow the CIDR when the network is shared with unrelated
services.

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

Each granian worker binds its own listening socket, so a respawn triggered by
`--workers-max-rss` can reset connections still queued in the retiring worker's accept
backlog. Granian only warns about this above one worker, and logs the resulting
handshake errors at `debug`, so a respawn-induced 502 leaves no server-side trace at the
default log level.

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
shell variables. Edits to the entrypoint script must preserve it.

Litestream applies R2's required signed-payload and concurrency settings automatically
from the endpoint hostname, so they are deliberately absent from the config.

`sync-interval` in `docker/litestream.yml` sets the worst-case data loss window. It is
not the only driver of billed request volume: L0 retention checks and L1 compaction run
on their own timers (`l0-retention-check-interval` and `levels`) regardless of write
rate.

Retention is configured in two places that must agree; see
[Backup Retention](#backup-retention).

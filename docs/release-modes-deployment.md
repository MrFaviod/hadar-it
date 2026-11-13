# Release-mode deployment: `dev`, `prod` and `demo`

Compose wiring for the three release modes of one codebase: per-mode Compose projects and
volumes, a mandatory preparation gate, the production upgrade/backup services,
a TLS entrypoint, and synthetic demo telemetry.

This document describes configuration, not a deployment: no image was built, no
service was started, and nothing here certifies that a mode runs end to end.
What was actually checked, and what remains unproven, is listed at the end.

Service commands (`prepare`, `backup-loop`, reset, seed, upgrade) belong to the
backend; their contracts live in `docs/backend/deployment-preparation.md`,
`release-modes.md`, `dev-mode.md`, `demo-reset.md`, `demo-public.md` and
`ops-backup-restore.md`.

## 1. `RELEASE_MODE` is required

`RELEASE_MODE` is an unprefixed process variable (deployment identity, not
`ITSM_` configuration). It is required in three places, so no path starts a
process that has not decided which mode it is:

| Where | Enforced how | Failure |
|---|---|---|
| Compose project name | `name: itsm-${RELEASE_MODE:?…}` | any `docker compose` command fails |
| Every application container | `RELEASE_MODE: ${RELEASE_MODE:?…}` in the shared environment | missing value fails at interpolation |
| `prepare`, API and worker | `itsm.release_mode` / `itsm.release_identity` | exit non-zero before serving |

Compose can only reject an **absent** value; it cannot judge `production` or
`Demo`. Validation of the value itself is the backend contract: `prepare`
refuses an absent or invalid mode with exit `1` before it touches a database,
and the API and worker do the same at startup.

There is no default and no `.env` file in this repository. Pass variables
explicitly and keep Compose away from any local `.env`:

```bash
docker compose --env-file /dev/null ...
```

## 2. One project and one volume set per mode

The project name carries the mode, so containers, the default network and every
named volume are mode-prefixed. A `dev` installation cannot reach a `prod`
volume by name, and two modes never share a database file, an attachment
directory or a task queue:

| Mode | Compose project | Database | Mode-owned volume |
|---|---|---|---|
| `dev` | `itsm-dev` | SQLite `/data/dev/dev.db` | `itsm-dev_dev-data` → `/data/dev` |
| `prod` | `itsm-prod` | external `ITSM_DATABASE_URL` (or the `local-postgres` profile) | `itsm-prod_app-data`, `…_task-data`, `…_attachment-data`, `…_backup-data` |
| `demo` | `itsm-demo` | SQLite `/data/demo/demo.db` | `itsm-demo_demo-data` → `/data` (the data directory is `/data/demo` inside it) |

`dev` and `demo` deliberately replace the inherited `app-data` / `task-data` /
`attachment-data` mounts with one owned directory each (`!override` in the
overlay), because their reset/preparation code requires storage under a single
validated root. The demo volume is mounted at `/data`, not at `/data/demo`: Docker
creates the mount point itself, and `python -m itsm.demo init` refuses an existing
directory, so the initializer creates `/data/demo` while its parent already exists.
The existing `migrate` service stays a manual `tools`-profile command and is not part
of any mode flow.

## 3. Starting a mode

```bash
# dev: local SQLite, seeded fictional data, loopback HTTP; owner from the wizard
RELEASE_MODE=dev \
ITSM_SELINUX_LEVEL=<reserved MCS level> \
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.dev.yaml up -d

# prod: external database, guarded upgrade, cookies over TLS
RELEASE_MODE=prod \
ITSM_DATABASE_URL='postgresql+psycopg://itsm:<password>@<host>:5432/itsm' \
ITSM_AUTH_ORIGIN=https://itsm.example.com \
ITSM_SELINUX_LEVEL=<reserved MCS level> \
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml up -d

# demo: one shared fictional installation, in-process 60-minute reset
RELEASE_MODE=demo \
ITSM_AUTH_ORIGIN=https://demo.example.com \
ITSM_SELINUX_LEVEL=<reserved MCS level> \
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.demo.yaml up -d
```

Optional profiles: `tls` (HTTPS entrypoint), `backup` (prod backups),
`monitoring-demo` (synthetic telemetry), plus the existing `local-postgres`,
`redis`, `search`, `monitoring*` and `tools` profiles.

A fresh `dev` or `prod` installation starts ownerless: complete the setup wizard
through the frontend edge, or use the explicit alternatives — `dev` accepts
`ITSM_DEV_ADMIN_PASSWORD` for the headless seed, and `prod` accepts
`bootstrap-superadmin` in the operations guide.

On a fresh checkout, build `backend` before a production `up`: the production
`initialize` image is `itsm-ops:0.1.0`, built `FROM itsm-backend:0.1.0` (section 6).
Preparation itself is the `initialize` service: `up` starts it in front of `backend`
and `worker`, and production creates no accounts, so the first owner is a separate
`bootstrap-superadmin` command documented in the [operations guide](operations.md).
After the first installation, an operator shell can export
`COMPOSE_FILE=compose.yaml:deploy/compose.prod.yaml` next to `RELEASE_MODE` and keep
using plain `docker compose --env-file /dev/null …` commands.

## 4. Variables per mode

Documented, not shipped: this repository contains no `.env` file and no
substitute for one. Use the process environment.

| Variable | `dev` | `prod` | `demo` |
|---|---|---|---|
| `RELEASE_MODE` | required `dev` | required `prod` | required `demo` |
| `ITSM_SELINUX_LEVEL` | required | required | required |
| `ITSM_DATABASE_URL` | overlay default `sqlite:////data/dev/dev.db` | **required** | overlay default `sqlite:////data/demo/demo.db` |
| `ITSM_AUTH_ORIGIN` | default `http://localhost:18080` | **required**, https | **required**, exact public origin |
| `ITSM_AUTH_COOKIE_SECURE` | `false` (loopback HTTP only) | `true` | base default `true` |
| `ITSM_DEV_ADMIN_PASSWORD` | optional: headless `dev.admin` seed; unset starts the wizard | – | – |
| `ITSM_DEMO_DATA_DIRECTORY` | – | – | `/data/demo` |
| `ITSM_OPS_BACKUP_ROOT` | – | `/data/backups` (backup service) | – |
| `ITSM_OPS_RETENTION_KEEP` | – | default `7` | – |
| `ITSM_OPS_BACKUP_INTERVAL_SECONDS` | – | default `86400`, minimum `60` | – |
| `ITSM_TLS_CERTIFICATE` | profile `tls` | profile `tls` | profile `tls` |
| `ITSM_TLS_CERTIFICATE_KEY` | profile `tls` | profile `tls` | profile `tls` |
| `ITSM_TLS_BIND` / `ITSM_TLS_PORT` | `127.0.0.1` / `18443` | same | same |
| `ITSM_PROMETHEUS_URL` | unchanged | unchanged | `http://demo-prometheus:9090` |
| Prometheus published port | – | – | none (private network only) |
| `ITSM_API_PORT` / `ITSM_FRONTEND_PORT` | `18000` / `18080`, loopback | same | same |

Demo also blanks every real integration channel it inherits
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ITSM_AI_CREDENTIAL_KEY`,
`ITSM_AI_BROKER_*`, `ITSM_SYSTEM_EXECUTOR_*`, `ITSM_HERMES_INSPECTOR_*`,
`ITSM_EXTENSION_VALIDATOR_*`, `ITSM_ALERTMANAGER_*`, `ITSM_MONITORING_SECRETS`,
`ITSM_MONITORING_INGEST_TOKEN`, `ITSM_MEILISEARCH_*`). An exported secret in the
operator's shell therefore cannot reach the public demonstration.

## 5. The preparation gate

`initialize` runs `python -m itsm.deployment prepare` once per deployment, and
both `backend` and `worker` depend on it with
`condition: service_completed_successfully`. A failed preparation stops the
project; the API never starts against unprepared data.

| Mode | What `prepare` does |
|---|---|
| `dev` | migrations, claim the database for `dev`, seed the fictional dataset (idempotent); create the `dev.admin` administrator only when `ITSM_DEV_ADMIN_PASSWORD` is set |
| `prod` | empty database: migrate to head; existing database: guarded upgrade (preflight, verified backup, Alembic, post-upgrade verification) |
| `demo` | migrate, claim the database for demo, validate the owned data directory, seed the fictional dataset and the `admin`/`admin` visitor (idempotent) |

A failure in any of these is a stopped deployment, not a partially prepared one:
production keeps its data and reports the backup and restore command.

### The setup service

`setup` is a separate, unprivileged Compose service (`python -m itsm.setup`) that
serves the first-start wizard. It depends only on initializing its private state
volume, never on the API or database, and it answers while both are absent. It has
no Docker socket, no host path and no published port: the frontend edge proxies
`/api/setup/v1/` to it. It writes its private setup volume, is the only writer of
the installation settings file (read-only for the API, worker and initializer),
and during verification it enqueues a real task on the worker queue and writes a
probe into the attachments volume. It has no Docker socket, no host path and no
published port, and it never edits this deployment.

The service starts disabled. The operator enables the wizard with
`python -m itsm.setup.cli enable-claim` inside the container, completes claim, AI,
storage and owner in the browser, and `complete` stops accepting bootstrap
mutations; `rotate-claim` replaces a lost claim and `recover` reopens a completed
wizard. The AI step needs `ITSM_AI_CREDENTIAL_KEYS` to seal a provider key and
can be deferred without it. Production narrows the wizard origin with
`ITSM_SETUP_ALLOWED_ORIGINS`, derived from `ITSM_AUTH_ORIGIN` in the overlay.
Removing or disabling `setup` after completion is pending: today it keeps
running, read-only and without bootstrap authority.

## 6. Production upgrade and backups

**Upgrade** is the `prepare` step of the one-shot `initialize` service in
`prod`, using the maintenance image and persistent backup volume (not the API
image). It refuses a database newer than the code, takes and verifies a
backup before migrating, and stops on failure with the exact restore command.

**Backups** run in a separate service (`--profile backup`) using its own image:

- image `itsm-ops:0.1.0`, `backend/Dockerfile.ops`, which is
  `FROM itsm-backend:0.1.0`. Build the application image first:
  `docker compose … build backend`, then `docker compose … build initialize`
  and `docker compose … --profile backup build backup`.
- artifact root `/data/backups` on the mode-owned `backup-data` volume;
  retention default `7` (+ the always-protected newest artifact), daily by
  default, minimum interval 60 s.
- `RELEASE_MODE=prod` is enforced by the command itself, so the service fails
  instead of writing artifacts when started in another mode.
- the ops recipe imports `pg_dump` and `pg_restore` plus private shared libraries
  from the same digest-pinned PostgreSQL **16.13** image as the local server.
  `POSTGRES_CLIENT_IMAGE` is a build argument in `backend/Dockerfile.ops`, but
  overriding it to another release (including 16.14) is deliberately refused.
  Build-time checks reject failed library audits and non-16.13 tools; a real
  image build and isolated dump/restore are still required before claiming
  compatibility. The backend base is a local tag, and Debian `mariadb-client`
  and `unixodbc` packages remain unpinned: this is not full OS reproducibility.
  There is **no `sqlcmd`**: SQL Server backups are not runnable from this image.
- `GET /api/v1/system/backups/status` requires reserved `system.view` authority.
  Ops publishes a sanitized atomic summary to `ITSM_OPS_STATUS_PATH`; the API
  reads `ITSM_BACKUP_STATUS_PATH` from a separate read-only status volume.
  Backup artifacts, engine tools and hashing remain exclusively in maintenance.

## 7. TLS entrypoint

`deploy/nginx-tls.conf` is mounted by the optional `proxy` service
(`--profile tls`). It terminates TLS for one origin and forwards `/api/` to the
backend and everything else to the frontend.

- certificates are supplied externally as PEM **content** through
  `ITSM_TLS_CERTIFICATE` and `ITSM_TLS_CERTIFICATE_KEY`; Compose materialises
  them as files at `/run/secrets/tls_certificate{,_key}`. Nothing is generated,
  no host certificate path is assumed, and an unset value is reported by Compose
  when the profile is used.
- `ITSM_AUTH_ORIGIN` must be the exact public origin served here, otherwise the
  backend's Origin/CSRF guard refuses cookie-authenticated mutations.
- the listener is `8080` inside the container and runs as the unprivileged
  nginx user (`101:101`, `cap_drop: ALL`, read-only root filesystem, tmpfs).
  It is published on `127.0.0.1:18443` unless `ITSM_TLS_BIND` is widened on
  purpose; for a public installation set `ITSM_TLS_BIND=0.0.0.0` deliberately
  and firewall host ports 18000/18080.
- response headers: HSTS, `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`, TLS 1.2+ with session tickets off. The transport limits
  (`3 r/s`, burst 60) only absorb anonymous floods; the backend's own request,
  body and session limits remain the authority. `client_max_body_size 12m`
  leaves headroom over the 10 MiB attachment limit, and the 130 s proxy
  timeouts leave headroom over the 120 s report rendering limit.
- there is no plain-HTTP redirect listener: the TLS port is the only published
  entrypoint for an exposed installation.

## 8. Synthetic demo telemetry

Enable `--profile monitoring-demo` with the demo overlay. Prometheus uses the
private Compose network, no published port and disposable tmpfs storage. The API
queries `http://demo-prometheus:9090`; no host gateway or volume access is needed.

`deploy/demo-prometheus.yml` discovers targets every 15 seconds through
`/api/v1/demo/telemetry/targets`. Each current fictional node carries `asset_id`,
`check_type=node`, `module=node` and a per-asset `__metrics_path__`. Metrics use
existing synthetic node exposition, never host/device measurements. Reset
recreates node monitoring profiles; discovery follows the new UUIDs and old
metric paths return 404. The routes exist only in a persisted demo installation.
The standalone legacy demo initializer/exporter still requires explicit setup.

No alerting, rules or remote_write are configured. No providers or external
notification channels are enabled. Synthetic telemetry is fictional and does not
measure the host or real devices.

## 9. What differs between the modes

| Aspect | `dev` | `prod` | `demo` |
|---|---|---|---|
| Database | owned SQLite under `/data/dev` | external, required URL | owned SQLite under `/data/demo` |
| Initial data | seeded fictional dataset; owner from the wizard or the headless `dev.admin` seed | empty, real data only | seeded fictional dataset + `admin`/`admin` |
| Sessions | loopback HTTP, cookies not Secure | Secure cookies, exact https origin | Secure cookies, exact public origin |
| Destructive reset | manual `itsm.devtools reset`, guarded | not allowed | automatic every 60 minutes, in-process |
| Task consumer | worker | worker | none by default (worker behind `demo-external-consumer`) |
| Providers, executors, installs | allowed by capability, unused unless configured | allowed | refused and blanked in the environment |
| Upgrades | `prepare` migrates | `prepare` runs the guarded upgrade | `prepare` migrates |
| Backups | – | `backup` service + `itsm.ops` | – |
| TLS | – | profile `tls` | profile `tls` (required for public exposure) |
| Telemetry | existing `monitoring*` profiles | existing `monitoring*` profiles | synthetic `monitoring-demo` |

## 10. Operational limits

- Alpha software is not a production-readiness guarantee. Rehearse TLS, upgrades and restore on a separate installation.
- The ops recipe does not back up SQL Server.
- Build the backend image before the ops image, which derives from it.
- Give each installation separate projects, storage, ports and SELinux labels.

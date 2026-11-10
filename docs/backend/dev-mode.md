# Development mode: initialize, inspect and reset a dev database

`python -m itsm.devtools` builds a database meant for development, reports it in
JSON and supports guarded reset and regeneration. It prepares fictional data
only in an owned development database, reports failures explicitly and refuses
to reset production storage.

The tool is a separate package (`itsm/devtools/`); it adds no startup hook, no
automatic migration and no new HTTP route.

## Prerequisites

- `RELEASE_MODE=dev`. Absent, `prod`, `demo` or any typo refuses every command
  with exit code 1, before any connection or file is touched.
- A **local** `ITSM_DATABASE_URL`: a SQLite file or a loopback host
  (`localhost`, `127.0.0.1`, `::1`). Remote databases are refused, so a dev
  process cannot reset a production database over the network.
- The canonical migrations run by the tool itself (`init`, `reset`). The API and
  worker still expect migrations to have been applied explicitly.
- Attachment and task state must live inside a directory whose name contains
  `dev`, or inside `ITSM_DEV_DATA_DIR`.
- The dev administrator password comes from `ITSM_DEV_ADMIN_PASSWORD` or, when
  that variable is empty, is generated and printed once on stdout.

```bash
export RELEASE_MODE=dev
export ITSM_DATABASE_URL="sqlite:///$PWD/.dev/dev.db"
export ITSM_DEV_DATA_DIR="$PWD/.dev"
export ITSM_ATTACHMENT_STORAGE_PATH="$PWD/.dev/attachments"
export ITSM_TASK_SQLITE_PATH="$PWD/.dev/tasks/huey.db"
export ITSM_AUTH_ORIGIN="http://localhost:18080"
export ITSM_AUTH_COOKIE_SECURE=false   # loopback HTTP only
read -rsp 'Dev admin password: ' ITSM_DEV_ADMIN_PASSWORD; echo; export ITSM_DEV_ADMIN_PASSWORD
```

## Commands

### `init`

Applies the migrations to head, claims the database for `dev` in
`deployment_identity`, creates the explicit dev superadmin and seeds the
canonical fictional dataset (`itsm.demo.seed`: two sites, two people, eight
documentation-only assets with `192.0.2.0/24` addresses, relationships,
incidents, maintenance plans and warranties).

```bash
.venv/bin/python -m itsm.devtools init --username dev.admin
```

A second `init` on the same database is idempotent: it returns
`status: "unchanged"`, creates no account and prints no password. It only
re-applies migrations, which is a no-op when already at head.

### `status`

Reports the environment as JSON and changes nothing (it never claims an identity
and never migrates):

```bash
.venv/bin/python -m itsm.devtools status
```

```json
{
  "status": "status",
  "mode": "dev",
  "target": "dev.db",
  "database": {"kind": "sqlite", "name": "dev.db", "url": "sqlite:////…/dev.db", "file": "/…/dev.db", "reachable": true},
  "identity": {"marker": "dev", "instanceId": "…", "createdAt": "…"},
  "demoMarker": false,
  "schema": {"current": "0029", "head": "0029", "status": "ok"},
  "counts": {"identity_identities": 2, "inventory_assets": 8, "…": 0},
  "reset": {
    "allowed": true,
    "reasons": [],
    "target": "dev.db",
    "requires": ["--yes-reset-dev-database", "--confirm dev.db"]
  }
}
```

`database.url` is the redacted URL (`safe_database_url`): a password never
appears. An unreachable database is reported honestly with `reachable: false`
and `reset.allowed: false` instead of failing, so a wrong URL is diagnosable.

### `reset`

Deletes the application rows, keeps the schema, restores the migrations'
reference rows and reseeds the canonical dataset.

```bash
.venv/bin/python -m itsm.devtools reset \
  --yes-reset-dev-database --confirm dev.db --username dev.admin
```

### `reset --regenerate`

Recreates the database from nothing: for a SQLite file the file is deleted and
migrations run again (`init` semantics, new inode, same path); for a server
engine the reflected tables are dropped on the loopback host and migrations run
again. Use it when `reset` is not enough or the schema is suspect.

```bash
.venv/bin/python -m itsm.devtools reset --regenerate \
  --yes-reset-dev-database --confirm dev.db --username dev.admin
```

Suggested workflow: `status` → confirm `target`, `identity.marker: "dev"` and the
redacted URL → `reset` (or `reset --regenerate`) → `status` → start the API and
worker with the same `ITSM_DATABASE_URL`.

## Safety rules

The destructive commands run these gates in order, all **before** any change:

| # | Gate | `init` | `status` | `reset` / `--regenerate` |
|---|------|--------|----------|--------------------------|
| 1 | `RELEASE_MODE` is exactly `dev` | required | required | required |
| 2 | Local database (SQLite file or loopback host) | required | required | required |
| 3 | Deployment identity row exists and is `dev` | claimed only when the database is empty/unmarked | reported only | required |
| 4 | `--yes-reset-dev-database` | — | — | required |
| 5 | `--confirm <database-name-or-file-basename>` matches the target | — | — | required |
| 6 | Attachment/task paths inside a `dev` directory or `ITSM_DEV_DATA_DIR` | — | reported in `reset.reasons` | required |

Consequences:

- an unmarked database, or one marked `prod`/`demo`, is refused even when it is
  local: only a database that dev claimed itself can be reset;
- a refused command changes nothing: tests compare the SQLite file bytes and the
  sentinel rows before and after every refusal class;
- a remote URL never opens a connection: the local guard runs first;
- the confirmation value is the redacted target name (`dev.db` for a SQLite
  file, the database name for a server engine), never a path outside the
  configured URL;
- data paths are resolved (symlinks included) before clearing; a path outside a
  development directory refuses the whole reset instead of being skipped.

Errors are one actionable line on stderr and exit code 1:

```text
error: database carries no deployment identity, so it was not claimed by a dev installation; next: run init for a new development database or point ITSM_DATABASE_URL at one (nothing was changed)
```

Add `--verbose` for the traceback of a refusal or of an unexpected failure.
Success prints JSON on stdout; warnings are written to stderr only.

## What `dev` enables

From the frozen capability matrix in `itsm.release_mode`. The flags are
permissions for features; they do not configure or enable a feature by
themselves.

| Capability | `dev` | `prod` | `demo` |
|---|---|---|---|
| `allow_system_operations` | yes | yes | no |
| `allow_extension_install` | yes | yes | no |
| `allow_external_notifications` | yes | yes | no |
| `allow_ai_providers` | yes | yes | no |
| `allow_agents_dev` | yes | no | no |
| `allow_seed` | yes | no | yes |
| `allow_destructive_reset` | yes | no | yes |
| `auto_migrate` | yes | no | no |

`dev` runs are additionally bound to a local database by
`itsm.release_identity.require_local_database`, and destructive commands require
the `dev` deployment identity plus the confirmation pair above.

## Reference rows preserved by `reset`

A plain `reset` keeps the rows the migrations insert, because the canonical
installation path expects them and the demo seed cannot recreate them:

| Table | Inserted by |
|---|---|
| `identity_roles`, `identity_role_policies`, `identity_security_settings` | `0002`, `0018`, `0021`, `0023` |
| `inventory_catalog` | `0004` |
| `inventory_code_sequences` (`__lock__`) | `0006` |
| `relationship_types` | `0007` |
| `notification_channels`, `notification_rules`, `notification_runtime_state` | `0017` |
| `ai_usage_quota_policy` | `0024` |

`tests/test_devtools_database.py` migrates a fresh isolated database and fails
when this set drifts from what the migrations actually insert. `--regenerate`
does not need the list: it rebuilds the schema and the migrations re-insert the
reference rows.

## Honest limits

- **Fictional business data is shared, credentials are not.** Development uses
  the fictional dataset with Spanish `· DEMO` labels, but creates a strict-password
  Superadmin (default `dev.admin`) and `dev.operator`. It does not create
  `admin/admin`, apply the demo password exemption, or write `demo_installation`.
  The deployment marker remains `dev`; other release modes refuse that database.
- **Migrations stay explicit for the API.** `init` and `reset` apply them; the
  API and worker are unchanged and still fail readiness on a non-head schema.
- **`ITSM_DEV_DATA_DIR` is read by the devtools package**, not by
  `itsm/config.py` (out of this task's edit surface). It is a local safety input
  for the CLI only; no other process reads it, and no second settings loader is
  introduced for application settings.
- **Edited reference rows survive a plain reset.** Role policies, notification
  defaults and similar configuration rows are treated as part of the schema; use
  `--regenerate` to return them to migration state.
- **External task/notification state is not cleared.** Only the SQLite task file
  under the dev data directory is deleted. A Redis/Postgres queue, a Meilisearch
  index or another external service must be cleaned by the operator.
- **Only SQLite is validated here.** The reflected-table `TRUNCATE`/drop paths
  for PostgreSQL, MySQL/MariaDB and MSSQL are implemented but were not executed
  against live servers in this task; MSSQL also needs `pyodbc`, which is not
  installed on this host.
- **No automatic reset.** There is no scheduler, no timer and no per-visitor
  isolation: the development database is shared and resets are manual.
- **A generated password is printed once.** It is on stdout only, but redirecting
  that output or reading it from a log leaks it; prefer
  `ITSM_DEV_ADMIN_PASSWORD`.

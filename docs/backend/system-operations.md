# System operations

System operations are installation-owned. They are exposed through the REST
API, the typed agent runtime, MCP tools and the agent integration catalog. The
public API payloads use camelCase; provider credentials never appear in any
payload.

## Authority

Six reserved permissions are granted only to a persisted human `superadmin`
(or a delegated machine whose active human delegator is a superadmin):

| Permission | Surface |
| --- | --- |
| `system.view` | status, configuration read, providers read |
| `system.configure` | configuration update |
| `system.providers` | provider update |
| `system.modules` | module list/update |
| `system.backup` | `backup.create` operation |
| `system.update` | `deployment.status` and `update.prepare` operations |

`admin`, `user`, `auditor` and machine identities that are not explicitly
delegated by a superadmin are denied. Authority is re-read on every request, so
revoking either the machine or its delegator takes effect immediately.

## REST API

All routes are under `/api/v1/system` and require an authenticated bearer or
session. Every mutation also requires the regular CSRF/mutation guard.

### `GET /status`

```json
{
  "ready": true,
  "checkedAt": "2026-10-26T12:00:00+00:00",
  "app": {
    "name": "itsm-backend",
    "version": "1.0.0",
    "mode": "production",
    "database": "postgresql"
  },
  "readiness": {
    "database": "ok",
    "migrations": "ok",
    "current": "0022",
    "head": "0022"
  },
  "executor": {
    "configured": true,
    "available": true,
    "actions": ["deployment.status", "update.prepare", "backup.create"],
    "detail": null
  }
}
```

`app.mode` is the factual process environment (`development`, `test` or
`production`). It is not an operator preference. When the executor is not
configured, `available` is `false`, `actions` is empty and `detail` explains why.

### `GET /configuration`

```json
{
  "deployment": {
    "classification": "production",
    "maintenanceWindow": "outside_business_hours",
    "database": "postgresql"
  },
  "executor": {"configured": true}
}
```

`deployment.classification` is the installation-owned classification
(`development`, `test`, `production`); `maintenanceWindow` is `anytime` or
`outside_business_hours`. `database` reports the configured backend without its
DSN.

### `PATCH /configuration`

Accepts only the fields being changed:

```json
{"deployment": {"classification": "production"}}
```

Any other field, including an attempt to set `database`, is rejected with 422.

### `GET /providers` and `PUT /providers`

`GET`:

```json
{
  "selected": {"provider": "openai", "model": "gpt-4.1-mini"},
  "selection": {
    "provider": "openai",
    "model": "gpt-4.1-mini",
    "source": "installation",
    "updatedAt": "2026-10-26T12:00:00+00:00",
    "updatedBy": "<identity id>"
  },
  "providers": [
    {
      "id": "openai",
      "label": "OpenAI",
      "credentialConfigured": true,
      "credentialEnv": ["OPENAI_API_KEY"]
    },
    {
      "id": "anthropic",
      "label": "Anthropic",
      "credentialConfigured": false,
      "credentialEnv": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
    }
  ]
}
```

`selected` is `null` when neither the persisted installation row nor the
`AGENT_MODEL` default selects an allowlisted provider/model. `PUT` accepts only
`provider` (`openai` or `anthropic`) and a bounded `model` string. Credential
values remain in the process environment; only the variable names and whether
one is set are exposed.

### `GET /modules` and `PATCH /modules/{module_id}`

`GET` returns the shared agent-integration catalog. `PATCH` accepts only
`{"enabled": boolean}`. The official `itsm` module cannot be disabled (409).

### `POST /operations`

Accepts only a fixed action and no arguments:

```json
{"action": "backup.create"}
```

```json
{
  "action": "backup.create",
  "state": "completed",
  "reference": "backup-20261026T120000Z",
  "exitCode": 0,
  "startedAt": "2026-10-26T12:00:00+00:00",
  "durationMs": 812,
  "result": {
    "status": "ok",
    "reference": "backup-20261026T120000Z",
    "artifact": {
      "name": "itsm-backup-20261026T120000Z.tar.gz",
      "bytes": 2048,
      "sha256": "<64 hex characters>",
      "verified": true
    },
    "restored": true,
    "files": 12,
    "revision": null,
    "message": null
  },
  "message": "backup.create completed"
}
```

`state` is `completed`, `failed` or `unavailable`. When the executor is not
configured or cannot be reached, `state` is `unavailable`, `result` is `null`
and `message` is bounded and redacted. A rejected action (unknown name, extra
fields, denied caller) produces no executor call.

## Typed tools

The following tools are registered in the agent runtime and MCP server and are
available to integrations whose module catalog permits ITSM:

- `get_system_status`
- `get_system_configuration`
- `configure_system_provider`
- `list_system_providers`
- `list_system_modules`
- `set_system_module`
- `prepare_system_update`
- `create_system_backup`

Both surfaces call the same `SystemService`; the tool layer never shells out or
constructs commands.

## Executor protocol

The web application talks to a separately run operator helper. Configure it with:

```text
ITSM_EXECUTOR_SECRET=<at least 16 characters>
ITSM_EXECUTOR_HOST=127.0.0.1
ITSM_EXECUTOR_PORT=8765
ITSM_EXECUTOR_TIMEOUT_SECONDS=60
ITSM_EXECUTOR_WORKDIR=/srv/itsm
ITSM_EXECUTOR_REDACT=secret,token,password
ITSM_EXECUTOR_ACTION_DEPLOYMENT_STATUS=<JSON argv array>
ITSM_EXECUTOR_ACTION_UPDATE_PREPARE=<JSON argv array>
ITSM_EXECUTOR_ACTION_BACKUP_CREATE=<JSON argv array>
```

Run the helper as `.venv/bin/python -m itsm.system.executor`; it prints one
`executor.ready` JSON line with its bound port. Configure the web process with
`ITSM_SYSTEM_EXECUTOR_URL`, `ITSM_SYSTEM_EXECUTOR_TOKEN` (the helper's shared
secret), and optionally `ITSM_SYSTEM_EXECUTOR_TIMEOUT_SECONDS`.

Each `ITSM_EXECUTOR_ACTION_*` value is a JSON array executed without a shell.
Only those configured argv arrays can run; requests carry no command, path or
additional argument. Children run in their own process group with a timeout,
bounded drained output, and the whole group is killed/reaped on completion or
timeout.

The helper exposes:

- `GET /healthz` (bearer required): `{"status": "ok", "actions": [...]}`.
- `POST /v1/actions/{action}` with an empty JSON object body.

A `200` response uses:

```json
{
  "action": "backup.create",
  "state": "completed",
  "reference": "backup-20261026T120000Z",
  "exitCode": 0,
  "startedAt": "2026-10-26T12:00:00+00:00",
  "durationMs": 812,
  "result": {
    "status": "ok",
    "reference": "backup-20261026T120000Z",
    "artifact": {
      "name": "itsm-backup-20261026T120000Z.tar.gz",
      "bytes": 2048,
      "sha256": "<64 hex characters>",
      "verified": true
    },
    "restored": true,
    "files": 12,
    "revision": null,
    "message": null
  },
  "message": "backup.create completed"
}
```

Action stdout must be one strict JSON object with only the documented fields.
Unrecognized fields, non-zero exit codes, malformed output or a timeout are
reported as `failed` with a bounded redacted message. Raw stdout/stderr and the
shared secret are never returned to callers or written to logs.

## Schema gate and restore stop order

The API and the task worker both refuse to serve a schema that is not at the
code's migration head:

- business routes answer `503 database_not_migrated` with the remedy
  (`python -m itsm.ops upgrade`), while `/api/v1/health/live` and
  `/api/v1/health/ready` stay reachable and report the migration state;
- the worker checks the same readiness in its startup hook and exits `2`
  instead of consuming tasks against an unknown schema;
- the check is re-evaluated at most every `SCHEMA_REVALIDATE_SECONDS` (2 s), so
  an upgrade performed while the process runs is picked up without a restart.

SQLite migrations run in one explicit transaction, so a failing revision no
longer leaves committed partial DDL; an interrupted run is recorded in the
backup root's `upgrade-attempt.json`, exposed as `status.upgradeAttempt`, and
refused on retry until the reported pre-upgrade backup is restored.

Restoring a SQLite database over a running process is refused (exit `3`) while
the API or the worker holds it, because their writes would go to the unlinked
file. The stop order is: stop the worker, stop the API, restore, start the API,
start the worker. The API revalidates the restored database's deployment
identity within 2 s and answers `503 release_identity_unavailable` if it belongs
to a different release mode.

## Production boundary

This repository ships the web-side contract, executor helper and fixed-action
allowlist. The production action commands, deployment host paths, trusted
release manifest and release signing are operator/deployment assets. Readiness
reports pending when pending migrations are not applied; it never pretends they
are current.

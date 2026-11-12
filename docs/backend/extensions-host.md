# Native extension host (SDK v2)

The host installs packages only after a persisted human Superadmin approves the
exact validated digest. Unlike SDK v1, approved Python **never runs in the API
or worker process**: each invocation spawns a restricted runner process, and
modules authored declaratively ship no code at all. See [the SDK guide](extensions-sdk.md)
for authoring, and `sdk/references/security.md` for the trust model and its
honest limits.

## Review and install

1. Submit a bounded ZIP as a candidate. Inspection checks the v2 manifest,
   paths, static import/call rules and SHA-256 without importing Python.
2. Run the server-owned isolated validator and bind its seven-key report to that
   candidate digest. A report entered by a unit test is not container-execution
   evidence.
3. Review `GET /api/v1/extensions/candidates/{id}`: `manifest`, version/digest,
   `runtime`, trust, core and extension permission deltas, migration plan,
   validation and rollback compatibility.
4. A human Superadmin calls `POST /api/v1/extensions/candidates/{id}/approve`
   with `{digest, expectedVersion}`. `expectedVersion` is the current integer
   installed **revision**, or `null` on first install, not a semantic version.
   Cookie mutations require Origin and CSRF.

Approval prepares storage (`<data_path>/<id>/data.sqlite3`), materializes the
package into a read-only per-digest cache, runs any declared migrations inside
the sandbox, and only then activates the new version. A machine, delegated
developer or model cannot approve, enable, disable, roll back or uninstall.

## Runtime: sandboxed

`itsm/extensions/runtime/` is a stdlib-only package. The host starts
`python -E -s -S -B runtime/runner.py` with an empty environment, `cwd` set to
the module data directory and a new session, then applies rlimits, `no_new_privs`,
Landlock and a seccomp-bpf deny-list **before** importing module code, and speaks
JSON lines over stdin/stdout. `-I` is replaced by `-E -s -S -B` because `-I` also
implies `-P`, which removes the runner's sibling modules from `sys.path`.

Landlock controls content access, so the deny-list also refuses every syscall
that changes inode metadata: `chmod`/`fchmod`/`fchmodat`/`fchmodat2`,
`utime`/`utimes`/`futimesat`/`utimensat` and the xattr family
(`setxattr`, `getxattr`, `removexattr`, `listxattr` and their `l`/`f`
variants), all returning `EPERM` on both supported architectures. A module runs
as the service user and therefore owns its inodes: without this, `chmod 000` on
a path it could not otherwise open (the core `app.db`, a foreign module
directory) would still take the product down. Denying the whole family is safe
because the runtime never changes its own permissions or timestamps.

The host enforces a wall-clock timeout, 1 MiB total output and per-line caps,
and at most 200 capability calls, and kills the process group. Module stdout and
stderr never reach the protocol channel. Unknown architecture or Landlock below
ABI 4 fails closed with `sandbox_unavailable` (HTTP 503).

## Runtime: declarative

A declarative module has no `backend.py`, migrations, schedules, subscriptions
or reconcile handler. Its `list`/`get`/`put`/`delete` operations execute in the
host process against the module's SQLite file, validating data against the
declared collection schema first. `put` and `delete` write, so they must declare
`"mutation": true`; the manifest is rejected otherwise and the host only opens
the store read-write when the invoked declaration carries the flag. `list` and
`get` must not declare it. `put` generates a UUID when `record_id` is
absent and `expected_version` implements compare-and-swap. A view's
`filterAsset`/`assetField` is a field name: for a declarative `list` it must be
a declared collection property and the host passes the selected asset's
permanent id inside the operation `filters`, so it needs no extra argument kind
and no module code.

## Data and migrations

Business data lives only in `<ITSM_EXTENSION_DATA_PATH>/<id>/data.sqlite3`
(WAL, `0700`/`0600`). The core database stores host metadata plus the
idempotency ledger `extension_core_calls`; it receives no extension business
rows. The managed `_itsm_records` table backs `context.store` with the same
`{id, version, data}` contract, `{items, total}` paging and compare-and-swap as
before; list filters compile to `json_extract` equality with validated keys.

`PRAGMA user_version` is the module data revision and is mirrored to
`extension_modules.data_schema_version`. Every upgrade first copies the live
file with the SQLite backup API to `<data>/<id>/snapshots/<revision>.sqlite3`.
A failed migration restores that snapshot and keeps the previous version and
data active. Rollback is limited to targets compatible with the current
revision; otherwise it requires `restoreData: true` plus `confirm: "<id>"` and
restores the recorded snapshot.

`POST /api/v1/extensions/{id}/uninstall {expectedVersion}` removes versions,
candidates, schedule state, migration rows, registered permissions and the
Superadmin role policies for those codes, records an audit event and **keeps**
the data directory. `GET /api/v1/extensions/{id}/status` reports status,
version, runtime, storage path and size, snapshots, event cursor, stalled flag
and sandbox availability.

## SDK v1 modules

Installed v1 modules are never executed again: discovery reports
`status: "requires_upgrade"`, invocation returns
`409 extension_requires_upgrade`, and schedules are not dispatched. Legacy rows
in `extension_collection_records` are copied into the module file only by an
explicit operator command:

```bash
python -m itsm.extensions relocate-legacy          # dry run
python -m itsm.extensions relocate-legacy --apply  # idempotent copy
```

The command reports `copied`, `unchanged` and `conflicts` per extension and
never deletes legacy rows. New v1 candidates are rejected at inspection with an
actionable message naming `sdkVersion: 2` and this command.

## Permissions, capabilities and idempotency

Declared `ext_<id_with_underscores>.<suffix>` permissions are registered in the
application database and granted to the Superadmin role as explicit audited
installation effects. Other roles receive no implicit grants. IdentityService
and the policy engine stay authoritative for discovery and execution.

Host capabilities (`assets.read`, `assets.write`, `incidents.read`,
`incidents.write`, `notify`) are a manifest allowlist served over RPC. They call
the canonical `InventoryService`, `InterventionService` and notification path
with the invoking principal, so Casbin authorization always applies; the host
never exposes SQL, sessions or internal tables. Mutations are allowed only from
`"mutation": true` operations, schedules, subscription handlers and reconcile,
and require an `idempotencyKey`. `(extension_id, principal actor id, key)`
stores the request hash and response in `extension_core_calls`: replaying the
same request returns the stored response, and reusing the key with a different
request returns `409 idempotency_conflict`. The principal is part of the key,
and a replay re-checks that principal's current permission for the capability,
so one identity cannot replay another's key to read the stored asset view and a
revoked permission turns the replay into a `403` rather than a cached success.

`context.principal` is a plain dict projection. `context.authorize(permission)`
checks current persisted authority; `context.db` is a `sqlite3` connection to
the module's own file only.

HTTP, chat and MCP use the same `ExtensionHostService.invoke` path. Disabled
modules immediately lose operations, tools, skills and UI. Operations and
schedules reauthorize persisted permissions after module loading and immediately
before dispatch, so a revocation during loading prevents execution.

## Events and reconciliation

The worker's existing periodic Huey seam runs `process_extension_events`
(`extension_events` task), which calls
`ExtensionHostService.dispatch_entity_events()` and then
`run_due_reconciles()`. For each enabled installed SDK v2 module with
subscriptions or collection references, the host polls `EntityEventFeed` with
consumer id `extension:<id>` and delivers events **in order**:

- sandboxed subscription: the declared handler receives `context.event` with
  `{id, sequence, type, entityType, entityId, occurredAt, changed}`;
- declarative reference policy: the host applies `flag`/`delete` to the module
  SQLite file, recording `_references` for flags.

The consumer is acknowledged only after the handler or policy succeeds, so
delivery is at-least-once; deduplicate by event `id`. On failure the host records
a closed code (`handler_error`, `authorization_denied`, `invalid_payload`,
`timeout`, ...), applies the feed's bounded backoff, and stalls the consumer
after the attempt budget. Disabled or uninstalled modules are not dispatched
and keep their cursor; re-enabling resumes from it. `POST
/api/v1/extensions/{id}/events/reset` (human Superadmin, `{expectedVersion}`)
clears a stalled budget, keeping the cursor and bumping the module revision.

Reconcile runs on the declared `intervalSeconds` and on demand via `POST
/api/v1/extensions/{id}/reconcile` (`{expectedVersion}`). For declarative
references the host batch-resolves up to 200 ids per entity type through
`itsm.events.references.resolve_entities` and rewrites `_references`; a
sandboxed module's reconcile handler runs with the same `assets.read` /
`assets.resolve` capabilities. Reconcile is idempotent and is the documented
repair path for any delivery gap.

`GET /api/v1/extensions/{id}/status` reports:

```json
{
  "id": "software-licenses",
  "status": "ready",
  "enabled": true,
  "version": "1.1.0",
  "digest": "<sha256>",
  "schemaVersion": 2,
  "runtime": "sandboxed",
  "revision": 3,
  "storagePath": "/data/extensions/data/software-licenses",
  "dataSizeBytes": 40960,
  "snapshots": [{"schemaVersion": 1}],
  "eventCursor": 12,
  "stalled": false,
  "events": {
    "consumer": "extension:software-licenses",
    "cursor": 12,
    "stalled": false,
    "lastError": null,
    "attempts": 0,
    "retryAfter": null,
    "state": "active"
  },
  "sandbox": {
    "available": true,
    "landlockAbi": 6,
    "arch": "x86_64",
    "detail": "landlock + seccomp-bpf runner available"
  }
}
```

`eventCursor` mirrors `events.cursor`; `events.lastError` is the closed failure
code and `events.retryAfter` an ISO timestamp while backoff is pending. A
Superadmin lists recorded contract gaps at `GET
/api/v1/extensions/contract-gaps`.

## Schedules and native notices

The parent worker calls `process_extension_schedules`, which builds the host and
runs `run_due_schedules()`. A compare-and-swap claim prevents two hosts
dispatching the same due slot; failures roll back module writes and use a
bounded retry delay. Notices go through the host-owned callback with the same
business session and are deduplicated per module/key/recipient; the host commits
that terminal effect.

```python
context.notify(
    recipient_ids=[context.principal["actor_id"]],
    key="expiry:record:2026-10",
    title="Vence pronto",
    body="Revisa el registro antes de que venza.",
    permission="ext_record_book.read",
    url="#/extensiones/record-book/records",
    idempotency_key="notice:expiry:2026-10",
)
```

## Known limits

These are deliberate, documented residuals. None of them is a hidden assumption
in the code.

- **The static admission scan is advisory, not a boundary.** It inspects
  `ast.Constant` strings and import names without importing the candidate, so
  string concatenation, `getattr`/`__import__` with computed names or code read
  from a package data file all pass. The kernel sandbox plus human exact-digest
  approval is the boundary; see the SDK guide.
- **The runner token is defence in depth, not a boundary.** The sandboxed
  module shares the runner process and UID, so code that walks the runner's
  stack frames can read the per-run token and post a result the host accepts.
  Forged *effects* still require a real account and its Casbin permissions, the
  host never grants authority from a frame alone, and a forged denial is
  refused; separating the protocol writer would need a second process, which
  this runtime deliberately does not add. Do not treat a module's own reported
  result as evidence of anything privileged.
- **Approval does not execute the module.** `approve_candidate` materializes and
  activates the exact digest but never imports `backend.py`, so a module whose
  backend cannot even be imported still installs with `status: "ready"`. The
  failure appears at the first invoke as `extension_handler_failed` (500) with
  the traceback kept server-side; a broken runtime is a runtime error, not an
  installation guarantee.
- **`rollback` with `restoreData: true` restores `data.sqlite3` only.** Any other
  file the module wrote under its own data directory (for example `files/**` or
  scratch output) is left in place, because the snapshot is a SQLite backup, not
  a directory image. Review or remove those files explicitly when the restored
  revision cannot read them.
- **Protocol frames are host-validated, not module-proof.** The JSON channel is
  private to the runner (`Context`, `Store`, `Assets` and `Incidents` expose
  methods, not the channel) and every terminal `result`/`error`/`fatal` frame
  carries a per-invocation token the host generated; a frame without the token
  is refused with `extension_handler_failed`, and a module-declared
  `permission_denied` that the host never issued is downgraded to
  `handler_failed`. Residual: module code still runs in the same UID and could
  guess and duplicate an inherited descriptor. A forged frame is then refused
  instead of trusted, but the module can consume a host reply or abort its own
  invocation. It cannot gain data or authority that way.


## Remote validator transport trust

`ITSM_EXTENSION_VALIDATOR_URL` accepts HTTPS, or authenticated HTTP only to a
literal loopback address (`127.0.0.1` / `::1`, not `localhost` or private LAN).
Configure it with the existing paired `ITSM_EXTENSION_VALIDATOR_TOKEN`; the client
uses the fixed `/validate` path, certificate verification for HTTPS, bounded
package/report sizes, no redirects or ambient proxies. No new PKI is required.
For loopback HTTP, bind the broker only to loopback and keep the shared token
private; remote operators must provide an HTTPS endpoint they trust.

The response comes over that authenticated configured transport and must match
the submitted package digest and report schema. A digest binds package bytes;
it does **not** authenticate an issuer or prove a malicious broker executed any
validator. TLS authenticates the configured endpoint, not its honesty. The
operator-selected validator remains a trusted service.

## Frame sequencing and navigation

The bridge ignores requests, resize and navigation until its existing `itsm:ready` handshake. Declared operations still go through the existing SDK/permission checks. Own declared page IDs and their exact hash links are allowed; host core destinations are admitted by the existing route parser/canonical serializer, including map/graph aliases. Unknown routes, trailing undeclared segments and undeclared/sibling extension pages are rejected without changing location. This is destination validation, not another authorization router.

Source/guest checks, minimal asset-ID initialization, wildcard `postMessage` delivery to the opaque origin and terminal second-load behavior remain. The opaque-origin race residual A36 is not claimed eliminated: `"null"` targetOrigin and an unauthenticated new channel are not substitutes.

# Extensions sdk

## Native integration contract

### Runtimes

Every manifest declares `sdkVersion: 2` and a runtime:

- `runtime: "sandboxed"` requires `backend.py`. The host never imports it. For
  each operation, schedule, migration, subscription or reconcile run it starts a
  fresh runner in the module data directory, applies rlimits (CPU, address
  space, file size, open files, `RLIMIT_CORE=0`), `PR_SET_NO_NEW_PRIVS`, Landlock
  (read/execute the stdlib, shared libraries, runner and read-only package
  cache; read/write only the module data directory; TCP denied; abstract UNIX
  sockets and signals scoped on ABI ≥ 6) and a seccomp-bpf deny-list (`socket`,
  `execve`, `ptrace`, `mount`, `bpf`, `keyctl`, `perf_event_open`, module
  loading, `io_uring`; `clone` only with `CLONE_THREAD`; `clone3` → `ENOSYS`).
  Landlock grants or denies *content* access only, so every syscall that changes
  inode metadata is denied separately: `chmod`/`fchmod`/`fchmodat`/
  `fchmodat2`, `utime`/`utimes`/`futimesat`/`utimensat`, and the
  `setxattr`/`getxattr`/`removexattr`/`listxattr` family with its `l`/`f`
  variants. Without those denials a module running as the service user owns the
  inode and could `chmod 000` a foreign path (including the core database) or
  re-stamp its timestamps. Every metadata attempt returns `EPERM`.
  Module code runs with an empty environment, so no `ITSM_*` variable, secret or
  database URL is visible.
- `runtime: "declarative"` ships no `backend.py`, no migrations, schedules,
  subscriptions or reconcile handler. Its `list`/`get`/`put`/`delete`
  operations execute in the host process against the module's own SQLite file.
  `put` and `delete` write, so they must declare `"mutation": true`; `list` and
  `get` must not. A manifest that breaks this is rejected at validation instead
  of silently running a write with read-only expectations.

Unknown architecture or Landlock below ABI 4 fails closed with
`sandbox_unavailable` (HTTP 503); declarative modules are unaffected.

### Backend, capabilities and durable data

`backend.py` exports `register(sdk)` and binds every declared handler through
`sdk.operation`, `sdk.migration`, `sdk.schedule`, `sdk.subscribe` or
`sdk.reconcile`. Operations, schedules, subscriptions and reconcile receive
`handler(context, **arguments)`; migrations receive `handler(context)`. Return
bounded JSON-serializable data and use the standard library only.

`context` is the whole integration surface:

- `principal` — a dict (`actor_id`, `kind`, `username`, `display_name`,
  `role_id`, `delegated_by`, `scopes`, `execution_id`, `authorization_ref`,
  `session_id`). Never take an actor, role or authority from operation
  arguments.
- `authorize(permission)` — live check through `IdentityService`.
- `store.get/list/put/delete` — the managed `_itsm_records` table in the module
  file, with `{id, version, data}` records, `{items, total}` paging and
  compare-and-swap on `expected_version`.
- `db` — a `sqlite3` connection to the module's own `data.sqlite3` only.
- `assets.get/search/resolve` and `assets.create/update/archive` —
  `assets.read`/`assets.write` capabilities routed to the canonical
  `InventoryService`.
- `incidents.get/list` and `incidents.create` — `incidents.read`/`incidents.write`
  capabilities routed to the canonical interventions service.
- `notify(...)` — the `notify` capability over the canonical notification path.
- `operation`, `schedule`, `event` — the current dispatch description.

`capabilities` in the manifest is an allowlist, not documentation: an
undeclared capability is refused before it reaches a canonical service. Every
capability call runs with the invoking principal, so authorization is identical
to REST, chat and MCP. Mutating capabilities are allowed only from operations
declared `"mutation": true`, from schedules and from subscription/reconcile
handlers, and they require an `idempotencyKey`. The host stores
`(extension_id, key, capability, request_hash, response)` in the core-owned
`extension_core_calls` table: the same key with the same request replays the
stored response, and the same key with a different request returns
`409 idempotency_conflict`.

Module business data lives in `<ITSM_EXTENSION_DATA_PATH>/<id>/data.sqlite3`
(WAL, directories `0700`, files `0600`); the core database receives no extension
business rows. `PRAGMA user_version` is the module data revision and is mirrored
to `extension_modules.data_schema_version`. Install prepares the file, upgrades
snapshot it with the SQLite backup API to
`<root>/<id>/snapshots/<revision>.sqlite3`, a failed migration restores the
snapshot and keeps the previous version active, and rollback to an incompatible
schema requires `restoreData: true` plus `confirm: "<id>"`. Disable and uninstall
never delete the data directory; `POST /api/v1/extensions/{id}/uninstall`
removes versions, candidates, migration rows, registered permissions and the
Superadmin grants for those codes while keeping the data.

### Events, references and reconcile

Core assets and incidents publish a transactional outbox
(`entity_change_events`, see [entity-events](entity-events.md)). An installed
module never reads the core database: the host delivers events to it.

- `subscriptions: [{"event", "handler"}]` accepts only the closed set
  `asset.created|updated|archived|restored|deleted` and
  `incident.created|updated`. Each handler runs in the sandbox with
  `context.event = {id, sequence, type, entityType, entityId, occurredAt,
  changed}` (`changed` holds field names only). Delivery is at-least-once and
  ordered per consumer; deduplicate with `context.event["id"]`.
- `collections[].references` declares a field that holds a permanent
  `asset`/`incident` id plus a host policy: `onArchive` `keep|flag`,
  `onDelete` `flag|delete`. Flagged records gain the host-managed
  `_references` object (`{"assetId": "archived"|"missing"}`) in `get`/`list`
  results; `delete` removes the record. The policy is idempotent and needs no
  module code.
- `reconcile: {handler, intervalSeconds}` (sandboxed only, minimum 300
  seconds) is the repair path. It runs periodically and on demand, receives no
  event, and should re-check every stored reference with
  `context.assets.resolve("asset", ids)` / `context.incidents` equivalents.
  `resolve` returns at most 200 ids per call and maps each id to
  `"active"|"archived"|"missing"`.

Events and reconcile are independent of the operation that wrote the record.
A crash between the core call and the local write cannot lose the reference:
delivery retries, and reconcile repairs any gap. Failed handlers get bounded
exponential backoff and then stall visibly; a Superadmin resets the consumer
with `POST /extensions/{id}/events/reset`.

#### Partial failures and retries

The recommended write order is **core call first with an idempotency key, then
the local write, then rely on reconcile**. If the sandbox dies after the core
mutation commits but before the local record exists, replaying the same
operation with the same `idempotencyKey` returns the stored core response
instead of creating a second asset, and the local write can proceed safely.
Example:

```python
asset = context.assets.create(values, idempotencyKey=f"license:{record_id}")
context.store.put("licenses", record_id, {"assetId": asset["id"], ...})
```

Never reverse the order and never call a mutating capability without a key that
is stable per business intent; a different request with a reused key is refused
with `409 idempotency_conflict` rather than silently applied.

The ledger is scoped to the caller: `(extension_id, principal actor id, key)`.
A replay returns the stored response only to the same principal, and only after
re-checking that principal's current permission for that capability, so a
second identity cannot replay someone else's key to read the asset view, and a
principal whose permission was revoked is refused (`403`) even with the exact
request.

### Contract gaps and the reference example

If a module needs a contract the SDK does not publish, do not bypass isolation:
call the development tool `extension_contract_gap` with `capability`, `reason`
and `example` (optionally `extensionId`). It records a host event, listable by a
Superadmin at `GET /api/v1/extensions/contract-gaps`, so the missing contract
can be reviewed. Static validation produces `contract_gap_required` for SQL text
targeting core tables or another file's `sqlite_master`, `ATTACH DATABASE`,
`itsm.*` imports, undeclared capabilities and private frontend imports.

The maintained reference package lives in
`itsm/extensions/sdk/examples/software-licenses/{1.0.0,1.1.0}`: a sandboxed
module with its own SQLite file, `licenses` and `assignments` collections
referencing `asset` ids, an asset panel and a licenses page, Casbin
`ext_software_licenses.read|write` permissions, subscriptions for
`asset.archived|deleted|restored`, a reconcile handler using `assets.resolve`,
and a 1.1.0 migration that adds `costCenter` to existing rows. Rollback to
1.0.0 restores the pre-upgrade snapshot. Walk through it with:

```text
.venv/bin/python -m pytest tests/test_extension_acceptance.py -q
```

### Declarative views

Pages, asset panels, widgets and asset actions are manifest descriptions
rendered by the host; SDK v2 executes no same-origin module JavaScript. A view
is `{"table": {...}}`, `{"form": {...}}` or `{"isolated": {...}}`, and every
view names a declared operation and a declared permission. `filterAsset` is a
field name, never a boolean: it says where the host puts the selected asset's
permanent id. A handler operation receives it as a declared top-level parameter
(`"asset_id"`); a declarative `list` names a declared collection property and
the host sends it inside `filters` (`{"assetId": "<id>"}`). `assetField`
follows the same rule for forms. The manifest is rejected at validation time
unless the named field exists on that exact operation. The host renders labels,
inputs, tables, empty and error states with its own components, so a module
cannot inject markup, CSS or a second design system. `frontend.contributions`
keeps the `add`/`hide` slot model; `add`/`replace` point at an isolated
component, `hide` needs no bundle.

### Isolated components

Only `view.isolated` (or a non-`hide` contribution) may ship
`frontend.entry: "frontend.js"`. The bundle loads in an iframe with
`sandbox="allow-scripts"`: opaque origin, no cookies, no host DOM, no storage,
CSP-restricted, with the host Vue runtime and component kit inlined. It
registers through `window.ITSMExtension.register({components})` and talks to the
host only with `postMessage`: `itsm:request` (own declared operations),
`itsm:navigate` (own page), `itsm:resize`, `itsm:ready` outward, and
`itsm:init`, `itsm:response`, `itsm:theme` inward. No message grants authority
and nothing is read from the parent window.

The review UI presents the exact version/digest, runtime, sandbox notice,
validation checks, permission additions, migration plan and rollback
compatibility. A persisted human Superadmin explicitly approves the package and
expected installed revision, and can later disable, roll back (with
`restoreData`/`confirm` when the schema is incompatible) or uninstall it. The
host checks that authority again at the lifecycle boundary. Source edits require
a new digest, validation and approval; there is no automatic activation or agent
installation command.

### SDK v1 modules

Modules installed by SDK v1 are never executed again. Discovery reports
`status: "requires_upgrade"` and invocation returns
`409 extension_requires_upgrade`. Their business rows stay in the legacy core
table until an operator copies them into the module SQLite file:

```bash
python -m itsm.extensions relocate-legacy          # dry run, no writes
python -m itsm.extensions relocate-legacy --apply  # idempotent copy
```

Copied, unchanged and conflicting records are reported per extension, and legacy
rows are never deleted. New v1 candidates are rejected at inspection with an
actionable message naming `sdkVersion: 2` and this command.

## Operator: prepare the offline validator image

`Dockerfile.extension-validator` reuses images that are already present and
explicitly identified; the validator build itself does not download packages.
Its base is the current public backend image, built by the operator from this
repository's `Dockerfile` and tagged `itsm-backend:0.1.0`. Build that image
first, record the exact local ID, then pass it explicitly:

```bash
docker build -t itsm-backend:0.1.0 .
BASE_ID="$(docker image inspect itsm-backend:0.1.0 --format '{{.Id}}')"
printf 'validator base ID: %s\n' "${BASE_ID}"
```

There is no default base ID and no private or machine-specific image. The
`VALIDATOR_BASE_ID` build arg is **required**: use the exact ID printed above
and compare it with the base you intended, because a tag alone is not
provenance. A missing or non-`sha256:` value makes the build fail before any
layer is produced. Changing the base is an operator review action, not a
candidate option.

The JavaScript engine is **Bun 1.4.2**, not Node, copied from the pinned
`oven/bun@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895`.
These are the complete, exact two build args — the validator build keeps
`--pull=false --network=none`:

```bash
docker build --pull=false --network=none \
  --build-arg "VALIDATOR_BASE_ID=${BASE_ID}" \
  --build-arg BUN_IMAGE=oven/bun@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895 \
  -f Dockerfile.extension-validator -t itsm-extension-validator:1 .
```

The resulting filesystem removes `/app` and `/data` and copies only SDK
contract/resources plus the fixed JavaScript engine. It has no application
checkout or application database. Rebuild after changing SDK validation/schema
resources; do not reuse a stale image report.

Each validation starts a unique container with `--pull=never`, no network,
read-only root, dropped capabilities, no-new-privileges, UID/GID 10001,
256 MiB memory with no extra swap, 0.5 CPU, 64 PIDs, 256 file descriptors and a
64 MiB noexec/nosuid/nodev temporary filesystem. No application mounts,
credentials, Docker socket or environment files enter it. Default wall-clock
limit is 60 seconds; output is bounded. The host accepts only bounded package
bytes and fixed SDK protocol metadata, never candidate argv/image/dependencies.

### API/worker without Docker access

Keep the application API and worker free of Docker sockets. Run the fixed
broker on the trusted validator host, using an operator-provisioned
`ITSM_EXTENSION_VALIDATOR_BROKER_TOKEN` of 32–512 printable ASCII characters:

```bash
python -m itsm.extensions serve-validator \
  --listen 127.0.0.1 --port 8766 \
  --image itsm-extension-validator:1 --timeout 60
```

The token is read from the environment, not a command-line argument, package,
request or log. Default bind is loopback. Configure the application with the
server **base** URL (`ITSM_EXTENSION_VALIDATOR_URL`) and the same token
(`ITSM_EXTENSION_VALIDATOR_TOKEN`); the fixed client appends `/validate`.
No path, query, fragment or URL userinfo is accepted. TLS verifies the server's
normal certificate chain. Plain HTTP is permitted **only for an explicitly
trusted local connection** such as loopback or an operator-isolated local
container-to-host link. Do not expose this privileged broker to an untrusted
network; use an operator-managed TLS endpoint for other connections.

The client uses direct stdlib HTTP connections: no ambient HTTP(S) proxies and
no redirects. The server checks the bearer secret in constant time before
reading the archive, limits headers/body/read time, accepts only the fixed
path and shares one bounded `ContainerValidator`. Requests cannot choose an
image, command, permissions or destination URL. Core permission codes are
operator-supplied canonical data. Without a configured broker, local validation
still fails closed when Docker/image execution is unavailable; no in-process
candidate execution or fabricated pass is substituted.

The shared application composition supplies the same canonical permission
catalogue to workspace preflight and local validation. Broker mode still
performs workspace preflight against that catalogue before sending bytes;
declaring a known code does not grant it, and unknown codes remain rejected.

## Validation evidence and errors

The fixed runner checks archive containment, canonical manifest/layout, Python
imports and registration, every declared operation, migrations, schedules,
actual package tests and either declarative-view wiring or JavaScript
syntax/registration. Declarative packages report host-side evidence instead of
a candidate subprocess. Each check name appears exactly once. The runner reports
the actual Python/jsonschema/JavaScript versions. Validation demonstrates
execution against the SDK contract; it does not prove every business rule, an
installation or a hostile-code sandbox. Review module tests and exercise the
real host lifecycle before approval.

### Static rules for sandboxed code

**These rules are advisory.** They inspect `ast.Constant` strings and import
names without importing the candidate, so they catch honest mistakes early and
give the author the public contract name instead of a private workaround. They
are not a security boundary and they are evadable by construction: concatenated
literals, `"".join(...)`, `getattr`/`__import__` with computed names, or code
loaded from a package data file all pass the scan. A module that passes is not
proven safe, and a module that fails is not necessarily malicious. The real
boundary is the kernel sandbox described above plus human exact-digest approval.
A false positive is possible in the other direction too (a literal that merely
looks like SQL, such as a capability name), so the check only fires when a
literal has both a SQL keyword and a structural keyword (`FROM`, `INTO`,
`TABLE`, `DATABASE`, `WHERE`, `SET`, `VALUES`, `JOIN`) and skips literals that
are capability names.

`backend.py` may not import `itsm`, `sqlalchemy`, `socket`, `subprocess`,
`ctypes` or `multiprocessing`, use relative imports, or call
`os.system`/`os.popen`/`os.exec*`/`os.spawn*`/`os.fork`/`ctypes.CDLL`. Rejection
messages start with `contract_gap_required:` and name the missing public
capability, so the fix is a contract decision rather than a private-structure
workaround. SQL DDL against core objects is impossible by construction: the
runner can open only its own module data file and Landlock denies every other
path.

The fixed reporting parent parses the archive/digest and performs static
checks without importing candidate Python. A bounded subprocess exercises the
candidate. Candidate logs are not report framing; exit without valid completion
evidence fails validation. Only expected per-check diagnostics are merged, never
a candidate-supplied top-level report. Candidate code can forge its own execution
evidence, including exiting after writing it. Only parent framing and static
checks are independent. Diagnostics and package tests are not security
attestations: same-UID subprocesses do not isolate hostile code from the reporting
process. The offline container protects the application; at runtime the sandbox
isolates the module, and human exact-digest approval is still required.

A report has exactly seven top-level keys:

```json
{
  "status": "passed",
  "digest": "<SHA-256 of the exact ZIP bytes>",
  "sdkVersion": 2,
  "checks": [{"name": "archive", "status": "passed", "detail": "..."}],
  "errors": [],
  "container": {"image": "...", "network": "none", "engine": "python ...; js bun ..."},
  "completedAt": "2026-10-28T10:00:00+00:00"
}
```

Unknown report fields, wrong digest/SDK version, malformed checks, invalid
completion time, or a passed status with errors/failed checks are rejected.
Timeout, excessive output, invalid archive paths, unsupported imports and
missing JavaScript execution produce failures, never compile-only success.
Validation metadata is stored outside editable source, and a user-supplied
report is never installation evidence.

| Symptom | Action |
| --- | --- |
| Runtime unavailable / exit 3 | Prepare the reviewed local image or trusted broker; do not add a Docker socket to the app. |
| Archive/layout failure | Keep only bounded declared package files; remove traversal/links/duplicate entries. |
| Manifest/permission failure | Read `manifest` and the current canonical permission catalog; do not invent core codes. |
| `sandbox_unavailable` (503) | The host kernel lacks a supported architecture or Landlock ABI ≥ 4; declarative modules still work. |
| `extension_requires_upgrade` (409) | The installed module came from SDK v1; rebuild it for SDK v2 and run `relocate-legacy`. |
| `idempotency_conflict` (409) | Reuse of a mutating capability key with different request content; make keys stable per business intent. |
| Registration failure | Bind every declared operation, migration, schedule, subscription and reconcile handler once with the exact manifest names. |
| Package test failure | Fix the package rule and its test, then repack and revalidate. |
| Stale validation or approval | Validate the current bytes and submit a new exact-digest candidate for human review. |

Continue with the bounded [quickstart](https://github.com/MrFaviod/hadar-it-backend/blob/master/itsm/extensions/sdk/references/quickstart.md)
and [host lifecycle guide](extensions-host.md).

# Public demo: restricted administrator and exposure limits

`RELEASE_MODE=demo` runs one shared, publicly reachable installation. A visitor
logs in with the published credentials `admin` / `admin` and receives a *demo
administrator*: real business capability, no control over the installation.
This document states exactly what that account can do, what the backend refuses,
and which limits protect the shared state. See `docs/backend/release-modes.md` for the
mode matrix itself.

Enforcement is backend-side. The UI may hide an action, but a hidden button is
not a control: every denied surface below also answers `403` to a direct HTTP
request. The demo identity is a normal `admin` role, so nothing is granted by
"being the demo"; what changes is that the guard removes the surfaces where an
`admin` would otherwise be able to damage or take over the installation.

## Accounts created by the demo seed

| Account | Role | Credentials | Purpose |
|---|---|---|---|
| `admin` | `admin` | `admin` / `admin` (published) | The public visitor. |
| `demo.installation-owner` | `superadmin` | random 64-character secret, generated, used once and discarded | Unavoidable last-superadmin invariant; cannot be logged into. |
| `<--username>` (CLI) | `admin` | operator-supplied at `python -m itsm.demo init` | Local operator access for telemetry and inspection. |
| `demo.operator` | `operator` | same password as the CLI account | Second business identity used by the seeded data. |

`bootstrap_superadmin` refuses to run once any human identity exists, and the
last active superadmin can never be removed. The demo therefore has to bootstrap
one superadmin first. Its password is generated inside the seed with
`secrets.token_urlsafe(48)`, used for the single in-seed login, and never
printed, stored or logged: the account exists to satisfy the invariant, not to
be used. No trace of the secret survives the seed call.

The visitor role is `admin`, not `superadmin`. The `admin` role already excludes
every `system.*` permission and `agents.providers.personal`, so extension
installation, system operations and personal AI providers are denied to the
visitor by the policy engine as well as by the demo guard.

### The `admin`/`admin` password waiver

Production password policy is 12–128 characters. Rather than weakening that
policy, `IdentityService` accepts a single explicit waiver value that the caller
must supply. Only the public-demo capability set produces it
(`visitor_password_waiver`), because it is derived from
`ModeCapabilities(allow_seed=True, allow_system_operations=False,
allow_extension_install=False, allow_external_notifications=False,
allow_ai_providers=False)` — the demo row of the matrix, which `prod` and `dev`
do not match. Production and development reject `admin` with `422`, and no
environment variable can enable the waiver.

## Seeded fictional dataset

The demo and development seeds share one dataset builder
(`itsm/demo/populated.py`, called from `itsm/demo/seed.py`). It is authored
entirely through the public services — `DirectoryService`, `InventoryService`,
`RelationshipService`, `RedundancyService`, `InterventionService`,
`MaintenanceService`, `AttachmentService`, `WarrantyService`,
`MonitoringService`, `WorkflowService` and `WorkspaceService` — so every row
carries the same history, audit and authorization records a real operation
produces. Nothing is inserted behind the services' back and no permission check
is bypassed. The one non-service step is the notification outbox drain: the seed
calls the same public `process_notifications` path the worker uses, because the
demo starts no worker, and every channel it can reach is internal.

Dates are computed from the demo clock at seed time (the start of a generation),
not hard-coded, so a reset re-creates a dataset that still contains overdue,
current and upcoming work an hour later. A reset regenerates every stored row,
including the completed import operation (new operation and row receipts) and the
attachment blobs under the configured attachment path inside the demo directory.

| Module | Seeded state |
|---|---|
| Directory | 2 sites with buildings, floors and four rooms; 2 departments; 5 people (technicians, an operator and a coordinator) with documentation-only email addresses and no phone numbers, since no reserved fictional phone range exists. |
| Inventory | 14 canonical assets across servers, virtual machines, switches, a router, IP cameras, a notebook, a printer and a monitor; most have a site, room, typed fields and a responsible person; several carry plan positions so the map is populated; one is in storage and unassigned. |
| Asset history | Assignment, return and reassignment of the notebook and printer, plus a site transfer of a virtual machine, each with reason, notes and a structured history entry. |
| Relationships | 13 typed edges (`hosted_in`, `connected_to`, `depends_on`, `protected_by`, `associated_with`) between known assets. |
| Redundancy | One active/passive group (two hypervisors) and one active/active group (two switches with traffic shares). |
| Incidents | Four incidents covering `open`, `in_progress` (acknowledged), `resolved` and `closed`, with affected assets and event history. |
| Interventions | Two corrective interventions attached to seeded assets. |
| Maintenance | Four plans covering overdue, upcoming, completed and postponed states, plus the template-derived virtual rows every asset shows. |
| Attachments | Three small synthetic local files (a PNG photo, a text receipt and a text document) uploaded through `AttachmentService` to the configured attachment path inside the demo directory; no external file is fetched and each reset regenerates the blobs. |
| Warranties | Five warranties across current, expiring and expired coverage, one of them referencing the seeded local receipt. |
| Monitoring | Three firing alerts ingested through the canonical Alertmanager ingest path on seeded assets (one acknowledged) plus a resolved cycle for a switch; the resolved cycle closes the earlier alert. |
| Notifications | The four alert events are drained through the internal notification path into the inbox of every active human identity. External channels remain suppressed at dispatch (`demo_external_delivery_blocked`); the seed never contacts a provider. |
| Imports | One completed CSV import (two new assets) executed through analyze → approve → execute, with the real operation, row receipts and audit records. Each reset regenerates the operation and receipts with new identifiers. |
| Workspace | One saved workspace view and a personal state with widget selection and last-view hints. |
| Reports | Built-in templates, labels and per-asset QR rendering work because they are synchronous. **No report job is seeded**: report jobs need the worker, and the demo seeds no queued or partially rendered job. A visitor who creates one sees it queued until a worker runs. |
| Agents, providers, extensions | Not seeded and still denied by `DemoRestrictionMiddleware` and the demo capability set; the dataset contains no model output, no provider credential and no installed extension. |

All synthetic identifiers use documentation-only addresses (`192.0.2.0/24`,
`example.invalid`). The seed performs no network call, model inference, package
installation or external delivery.

## Denied surfaces

The guard is one middleware installed in `create_app` only when the capability
set is the public demo (`itsm/demo/restrictions.py`). It works on the relative
API path (`itsm.api_prefix` is stripped), matches whole path segments, and
answers `403` with the stable code `demo_restricted`:

```json
{"error": {"code": "demo_restricted", "message": "this capability is disabled in the public demonstration"}}
```

| Surface | Method | Why |
|---|---|---|
| `/system/*` (status, configuration, providers, modules, operations) | all | Host and internal resources, privileged executor. |
| `/extensions/*` (candidates, approve, enabled, rollback, invoke, frontend) | all | Code installation and rollback. |
| `/agent/integrations/*` (modules, targets, instances, defaults, receipts, install) | all | Provider/module wiring. |
| `/agent/providers/*`, `/agent/gateway/*` | all | Provider credentials and bearer leases. |
| `/agent/chat`, `/agent/sessions/*` | all | Model inference on the installation's accounts. |
| `/notifications/channels`, `/notifications/rules` | mutation | External delivery configuration; the native inbox stays. |
| `/notifications/channels` payload naming an external transport | `POST` | A channel created with `smtp`/`webhook`/… is refused even if a rule was already disabled. |
| `/monitoring/exporters`, `/monitoring/profiles/*`, `/monitoring/assets/*` | mutation | Scrape/export configuration. Monitoring reads and the Prometheus metric endpoint keep working. |
| `/workspace/integrations` | mutation | AnyDesk/RMM integration targets. |
| `/identity` (users, roles, policies, settings) | mutation | Escalation, lockout of other visitors, and session-policy changes. |
| `/tasks/demo` | `POST` | Arbitrary background work on the shared queue. |
| `/openapi.json`, `/docs`, `/redoc` | `GET` | The API description and interactive docs are not published in the public demo; they answer `404`. |

Everything else stays available to the visitor: assets, catalog, people,
departments, locations, relationships, redundancy, maintenance, interventions,
warranties, attachments within quota, workflow operations, reports, dashboard,
appearance, search, monitoring reads, notification inbox, `/health/*`, the
identity read views (`/identity/state`, `/identity/catalog`, `/identity/audit`)
and `GET /tasks/{id}`.

**Fail closed.** The guard is a prefix deny-list, so a *new* route added under a
protected prefix is denied without touching the guard. `prod` and `dev` build
`demo_restrictions = None`: no guard is installed and those modes behave exactly
as before.

Two further demo-only forces apply regardless of route:

- `allow_external_notifications` is false, and `NotificationService` suppresses
  every non-`internal` channel at dispatch time (`demo_external_delivery_blocked`).
  The demo guard additionally refuses to create such a channel through HTTP.
- Provider credentials (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`) are irrelevant: the demo capability set denies AI
  providers, and the guard blocks the provider/gateway routes. Nothing in the
  visitor flow reads those keys.

## Exposure limits

`itsm/limits.py` builds one limiter per process, again only in the public-demo
capability set (`app.state.demo_limits`); `prod` and `dev` keep `None` and are
not throttled. Values come from `ITSM_DEMO_*` settings:

| Setting | Default | Effect |
|---|---|---|
| `ITSM_DEMO_RATE_LIMIT_PER_MINUTE` | 180 | Token-bucket refill for ordinary requests, per client key. |
| `ITSM_DEMO_RATE_LIMIT_BURST` | 60 | Bucket capacity; the burst a client may spend at once. |
| `ITSM_DEMO_LOGIN_RATE_PER_MINUTE` | 10 | Stricter bucket for `POST /auth/login`. |
| `ITSM_DEMO_LOGIN_RATE_BURST` | 5 | Login burst capacity. |
| `ITSM_DEMO_MAX_REQUEST_BODY_BYTES` | 1 MiB | Request body cap (`413 payload_too_large`). |
| `ITSM_DEMO_ATTACHMENT_MAX_BYTES` | 2 MiB | Attachment body cap, applied on top of `attachment_max_bytes`. |
| `ITSM_DEMO_ATTACHMENT_QUOTA_BYTES` | 100 MiB | Total live attachment bytes (`413 storage_quota_exceeded`). |
| `ITSM_DEMO_MAX_ACTIVE_SESSIONS` | 50 | Active session cap; the oldest sessions are revoked on each new login. |
| `ITSM_DEMO_MAX_IN_FLIGHT` | 8 | Concurrent request cap (`503 server_busy`). |
| `ITSM_TRUSTED_PROXY` | `false` | Honour the rightmost `X-Forwarded-For` entry for the client key and let the ASGI server trust forwarded headers. |

Responses that reject carry `Retry-After` and `Cache-Control: no-store`; the
body is the usual `{"error": {"code", "message"}}` envelope with the codes
`rate_limited`, `login_rate_limited`, `payload_too_large`,
`storage_quota_exceeded` and `server_busy`.

Requests run concurrently, not one at a time: `ITSM_DEMO_MAX_IN_FLIGHT` caps how
many are served at once, and a slow upload does not block the next visitor. The
hourly reset is the only exclusive operation: it stops admitting requests, drains
the ones in flight, and answers anything that arrives meanwhile with
`503 demo_reset_unavailable` and `Retry-After` instead of queueing it.

`X-Forwarded-For` is attacker-controlled, so both layers ignore it unless the
deployment declares a proxy. Start the API with the documented launcher
(`python -m itsm.main`, which the demo Compose overlay uses) rather than a bare
`uvicorn itsm.main:app`: the launcher passes `proxy_headers=ITSM_TRUSTED_PROXY`
to uvicorn, while stock uvicorn already trusts forwarded headers from a loopback
peer and would let a visitor mint a fresh rate-limit bucket with a fake header. A
bare `uvicorn itsm.main:app` needs `--no-proxy-headers` for the same default.

Set `ITSM_TRUSTED_PROXY=true` only behind the reverse proxy that terminates TLS
and overwrites the header, and point uvicorn's `FORWARDED_ALLOW_IPS` at that proxy
address so only the real hop is trusted. With trust enabled the *rightmost* entry
is used — the one the proxy appended — never the client-supplied leftmost value.

## Honest limitations

- **One shared state.** There is no per-visitor isolation. Every visitor
  sees and can edit the same fictional dataset, so one visitor can remove what
  another created, and the attachment quota and session cap are global.
  `demo reset` is the recovery path.
- **The limiter is per process.** Buckets, in-flight slots and the session cap
  live in the API process. With several workers each worker enforces its own
  budget, so the effective rate multiplies by the worker count. A single worker
  is the honest configuration for the public demo. The `api.lock` file refuses a
  second API *process* on the same data directory (so two schedulers never reset
  concurrently), but it cannot stop a second worker inside one process; a shared
  limiter store would be a different design decision.
- **The session cap is evict-oldest, not refuse-new.** A script that logs in
  repeatedly can push other visitors out; it cannot exceed the cap. Session rows
  are revoked, not deleted, so the audit trail is preserved.
- **The in-process body cap buffers the request.** Bodies are read into memory
  up to the configured maximum, so the cap bounds memory per request, not total
  memory; `ITSM_DEMO_MAX_IN_FLIGHT` is what bounds it in aggregate.
- **TLS, security headers, HSTS and the public hostname are not handled here.**
  They belong to the reverse proxy in . The demo must not be exposed directly
  on plain HTTP.

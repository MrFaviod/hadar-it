# Infrastructure and identity operations

Run commands from `asset/`. Root Compose references the two independent component checkouts; cloning root alone does not fetch them. Read backend/README.md for API/task payloads and native Python commands. The React/Vue renderer uses real FastAPI login, users, roles and sessions. Phase 3 adds basic SQL inventory and conversation; other unimplemented domain data remains prototype-only. Current work prioritizes the integrated persistent database, not external engine certification.

## Configuration without secret files

The human selected documentation of variables instead of creating `.env` / `.env.example`. Commands explicitly disable Compose's implicit `.env` loading. Supply variables via the calling environment or your approved external secret-management mechanism; do not put production credentials in Git, terminal transcripts or example files. URL-encode credentials in database URLs. Container environment is visible to Docker administrators: this is not a secret vault.

| Variable | Default / meaning |
|---|---|
| `ITSM_AUTH_ORIGIN` | Exact browser origin; Compose default http://localhost:18080. Match the browser hostname. |
| `ITSM_AUTH_COOKIE_SECURE` | true; explicitly false only for isolated/local HTTP. Use HTTPS otherwise. |
| `ITSM_BOOTSTRAP_PASSWORD` | External initial password for explicit administrator CLI; no default account. |
| `ITSM_AGENT_MODEL` | Empty disables inference; server-selected `provider:model`, e.g. `openai:gpt-4.1-mini` or `anthropic:claude-sonnet-4-5`. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Provider-specific external credential; never browser input, committed configuration or a tool argument. |
| `ITSM_AGENT_OPENAI_BASE_URL` | Optional server-owned OpenAI-compatible endpoint; never accepted from chat. |
| `ITSM_AGENT_MAX_STEPS` / `ITSM_AGENT_MAX_HISTORY_MESSAGES` / `ITSM_AGENT_MAX_OUTPUT_TOKENS` | `8` / `20` / `1024`; bounded inference/tool interaction. |
| `ITSM_DATABASE_URL` | PostgreSQL SQLAlchemy URL, defaults to local `postgres` with user/database `itsm` and externally supplied `ITSM_POSTGRES_PASSWORD` |
| `ITSM_POSTGRES_PASSWORD` | No built-in password; required for the local PostgreSQL profile |
| `ITSM_TASK_STORAGE` | `sqlite`; alternatives `redis` / `postgres` |
| `ITSM_TASK_SQLITE_PATH` | Compose sets `/data/tasks/huey.db`, separate from `/data/app/itsm.db` |
| `ITSM_ATTACHMENT_STORAGE_PATH` | Compose sets `/data/attachments`, backed by independent `attachment-data` |
| `ITSM_ATTACHMENT_MAX_BYTES` | `10485760` (10 MiB), adjustable from 1 byte to 50 MiB |
| `ITSM_TASK_REDIS_URL` | `redis://redis:6379/0`; optional profile or external Redis |
| `ITSM_TASK_POSTGRES_DSN` | Separate Huey PostgreSQL DSN; never infer queue choice from main SQL engine |
| `ITSM_TASK_RETRIES` / `ITSM_TASK_RETRY_DELAY_SECONDS` | `2` / `1`; bounded demo retry policy |
| `ITSM_DEMO_PERIODIC_MINUTES` | `0` disables the periodic demo; 1–60 enables a worker schedule |
| `ITSM_LOG_LEVEL` | `INFO`; structured application/worker logs |
| `ITSM_MEILISEARCH_URL` | Empty selects canonical SQL search. Optional HTTP(S) engine base URL; no embedded credentials, query or fragment. Engine loss falls back to SQL. |
| `ITSM_MEILISEARCH_API_KEY` | Optional secret for an external engine; Compose defaults to externally supplied `ITSM_MEILI_MASTER_KEY` for its search profile. |
| `ITSM_MEILISEARCH_HTTP_TIMEOUT_SECONDS` | `5`; bounded 1–60 seconds for engine requests. |
| `ITSM_SEARCH_INDEX_NAME` | `itsm_entities`; endpoint-safe index name, 1–64 characters. |
| `ITSM_SEARCH_SYNC_BATCH_SIZE` | `100`; bounded 1–500 durable outbox rows per Huey synchronization batch. |
| `ITSM_SERVICE_REDIS_URL` | Optional descriptor, not a readiness dependency. |
| `ITSM_PROMETHEUS_URL` | Engine base URL used by the monitoring adapter. Compose default `http://prometheus:9090` for the local profile; set an external HTTPS URL instead. An empty or unreachable engine is reported as unavailable, never as every device down. Credentials/query/fragment are rejected; use the token variable. |
| `ITSM_PROMETHEUS_TOKEN` | Optional bearer for an external Prometheus API. Secret; never in URLs, logs or Git. |
| `ITSM_ALERTMANAGER_URL` | Empty disables native Alertmanager mode. Set `http://alertmanager:9093` with the local profile, or the external address. |
| `ITSM_ALERTMANAGER_TOKEN` | Optional bearer for the Alertmanager API (silences) when your instance enforces auth. |
| `ITSM_MONITORING_DISCOVERY_TOKEN` | Shared bearer for Prometheus HTTP service discovery and configuration metrics. Required by the local Prometheus profile; supply it externally. |
| `ITSM_MONITORING_INGEST_TOKEN` | Bearer Alertmanager presents to the ITSM webhook. Required when AM posts; distinct from the discovery token. |
| `ITSM_MONITORING_HTTP_TIMEOUT_SECONDS` | `10`; bounded 1–60 seconds for engine/Alertmanager calls. |
| `ITSM_MONITORING_POLL_SECONDS` | `60`; bounded 60–3600; Huey polling cadence when native Alertmanager mode is off. |
| `ITSM_MONITORING_PUBLIC_URL` | User-facing base used in links, default `http://localhost:18080`. |
| `ITSM_MONITORING_SECRETS` | JSON object mapping an Apprise reference to its full URL/token, supplied externally. API responses expose only whether a reference is configured. |
| `ITSM_SNMP_AUTHS` | YAML `auths:` document for the SNMP Exporter, supplied externally and projected as a Compose secret file for `monitoring-snmp`. Required by that profile; never committed, printed or stored in ITSM. |
| `ITSM_NOTIFICATION_RETENTION_DAYS` | `90`; bounded 1–3650; delivered/failed notification and inbox retention. |
| `ITSM_API_PORT` / `ITSM_FRONTEND_PORT` | Loopback `18000` / `18080` |
| `ITSM_PROMETHEUS_PORT` | Loopback `19090` |
| `ITSM_PROMETHEUS_RETENTION` | `7d`; valid Prometheus retention duration; ignored by an external engine |
| `ITSM_ALERTMANAGER_PORT` | Loopback `19093` for the optional local Alertmanager |
| `ITSM_MEILI_MASTER_KEY` | Required only for the optional local search profile, externally supplied; forwarded to the API/worker as the engine API key unless explicitly overridden. |

### Integrated database first

The default remains persistent SQL search with no extra service. An installation
may opt into Meilisearch for relevance; SQL still rehydrates and authorizes every
hit, and outages retain SQL search. Existing PostgreSQL configuration is optional.

### Local PostgreSQL (optional)

Supply `ITSM_POSTGRES_PASSWORD` externally first, then:

```bash
docker compose --env-file /dev/null --profile local-postgres up -d --wait postgres
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose account details:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# Only for local plain HTTP; production must retain secure cookies with HTTPS:
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

Migrations run explicitly once before API readiness, not concurrently from API/worker entrypoints. Frontend: `http://127.0.0.1:18080`; API OpenAPI: `http://127.0.0.1:18000/docs`. Basic services do not require Redis, Meilisearch or Prometheus.

### External main SQL / persistent SQLite

Provide `ITSM_DATABASE_URL` for the chosen external database; omit `local-postgres`. Example non-secret local SQLite selection:

```bash
export ITSM_DATABASE_URL=sqlite:////data/app/itsm.db
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose account details:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# Only for local plain HTTP; production must retain secure cookies with HTTPS:
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

SQLite main data persists in `app-data`; task queue/results in `task-data`. These are separate files and volumes. Both backend mounts use lowercase `:z`: API, migration and worker intentionally share their SELinux label. Do not substitute private `:Z` or disable SELinux. A private MCS label can make SQLite fail with `unable to open database file` despite correct UID/mode, depending on which container starts first. Queue SQLite must remain local to one Docker host, shared between API and worker, not NFS or a multi-host cluster. The default worker has one thread/process; scale only after testing queue/storage and business idempotency. Main SQL dialect configuration is not proof of live engine compatibility; consult the backend validation matrix.

### Optional services

```bash
docker compose --env-file /dev/null --profile redis up -d redis
# Only when ITSM_MEILI_MASTER_KEY is supplied externally:
docker compose --env-file /dev/null --profile search up -d meilisearch
```

Selecting the Redis profile alone does **not** change the queue; set `ITSM_TASK_STORAGE=redis` and its URL, then recreate API/worker intentionally. Likewise PostgreSQL queue uses `ITSM_TASK_STORAGE=postgres` plus its own DSN. Queue tables/storage lifecycle belongs to Huey, separate from main Alembic migrations.

For optional search, set `ITSM_MEILISEARCH_URL=http://meilisearch:7700` and supply
the key externally before intentionally recreating API/worker. The real Huey
consumer processes transactional search outbox rows and bounded retries. An
administrator can inspect `/api/v1/search/status` and request `POST /search/rebuild`
or `/search/sync` using the existing Origin/CSRF guards. Rebuild prepares a temporary
index and swaps only after successful indexing; a failed rebuild keeps the prior
index. No engine is needed for SQL search, favorites or saved views.

### Monitoring topology

Each optional profile starts one service; enable only what the installation monitors.
No profile is a readiness dependency, and a decommissioned profile never fabricates data.

| Service | Profile | Port | Storage / notes |
|---|---|---|---|
| Prometheus | `monitoring` | loopback `19090` | `prometheus-data`, retention `ITSM_PROMETHEUS_RETENTION` |
| Blackbox Exporter | `monitoring-blackbox` | internal `9115` | ICMP/HTTP(S)/TCP/DNS probes; `NET_RAW` for ICMP |
| SNMP Exporter | `monitoring-snmp` | internal `9116` | switches, gateways, routers; auths supplied externally |
| Node Exporter | `monitoring-node` | host `9100` | host network/PID, read-only `/proc`, `/sys`, `/` |
| Alertmanager | `monitoring-alertmanager` | loopback `19093` | `alertmanager-data`; native silences |

```bash
# Tokens come from your external secret manager; do not export them in shared shells.
# ITSM_MONITORING_DISCOVERY_TOKEN: Prometheus -> ITSM discovery/config endpoints
# ITSM_MONITORING_INGEST_TOKEN:    Alertmanager -> ITSM webhook
docker compose --env-file /dev/null \
  --profile monitoring --profile monitoring-blackbox \
  --profile monitoring-snmp --profile monitoring-node \
  --profile monitoring-alertmanager up -d
```

Start a subset when an installation only needs HTTP probes, only switches, or only host
metrics. `docker compose config` succeeds without the tokens; `up` of a profile that
mounts a token secret requires its environment variable. The API and worker must carry
the same token values so the discovery/metrics endpoints and webhook accept the callers.
`monitoring-snmp` additionally requires `ITSM_SNMP_AUTHS` (see below); without it the
exporters fail at startup rather than probing with an empty credential.

Images are pinned by tag and registry digest:

| Image | Digest |
|---|---|
| `prom/prometheus:v3.14.0` | `sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0` |
| `prom/blackbox-exporter:v0.29.1` | `sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13` |
| `prom/snmp-exporter:v0.30.1` | `sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859` |
| `prom/node-exporter:v1.12.1` | `sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0` |
| `prom/alertmanager:v0.34.1` | `sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a` |

#### Discovery, rules and retention

Prometheus discovers targets from ITSM over native HTTP service discovery, one endpoint
per check type (`icmp`, `http`, `tcp`, `dns`, `snmp`, `node`, `windows`), refreshing every
60 seconds. Adding, changing or disabling an asset changes the next discovery response;
there are no per-device files, target lists or reload steps. An asset that is disabled,
targetless or unmonitored is absent, which is not the same as offline.

`deploy/prometheus.yml` also scrapes the ITSM configuration endpoint as series: per-asset
enabled flag, thresholds and minimum-duration preset. `deploy/prometheus-rules.yml` is a
fixed versioned bundle installed once in the engine. It uses literal native `for`
durations for the supported presets (0/60/300/900 seconds) and stays silent for any
target not on that preset; no generated rule files, Huey reloads or arbitrary durations
are claimed. Intermittent behavior uses `changes()` over real probe results and
discovered scrape (`up`) series, not a synthetic state machine. Threshold comparison
uses normalized units: latency seconds, CPU/memory/disk percent, temperature Celsius.
Scrape cadence defaults to 60 seconds per job. The per-asset `interval_seconds` label is
honored natively for the supported presets (30/60/300/900 seconds) through the special
`__scrape_interval__` relabel target; an absent or unsupported value keeps the job's 60
seconds, and the explicit 10-second scrape timeout stays below the smallest preset. The
target API exposes the effective `scrapeInterval`/`scrapeTimeout` per active target
(`discoveredLabels.__scrape_interval__` still shows the job default), while the
`itsm_monitoring_check_interval_seconds` configuration series mirrors the same setting.

Prometheus stores its own TSDB in `prometheus-data`; retention is configurable and
independent of inventory and notification retention. An external Prometheus keeps its
own storage and retention.

#### Native Alertmanager mode

With `monitoring-alertmanager` enabled, set `ITSM_ALERTMANAGER_URL` (and
`ITSM_ALERTMANAGER_TOKEN` only if your Alertmanager enforces auth). Alertmanager is then
the sole authority for grouping, inhibition and silences; ITSM creates and expires
silences through its API instead of keeping a second suppression system. Prometheus posts
standard v4 webhooks to the ITSM backend, authenticated by `ITSM_MONITORING_INGEST_TOKEN`;
the adapter accepts a bounded body, keys events by stable asset identifier and rejects
unknown assets. Acknowledgement never resolves an alert, and recovery never closes a
linked incident.

Without Alertmanager, ITSM polls native Prometheus alerts through the existing Huey
schedule and applies suppression locally for notifications only. Inventory, monitoring
configuration and device state remain usable with no engine and no Alertmanager at all;
missing engine data is reported as unavailable or no-data, never as devices down.

Do not duplicate grouping/inhibition/silence rules in two systems. The local
`deploy/alertmanager.yml` is deliberately minimal: group by `asset_id`, suppress a
warning while a critical exists for the same asset, and route to the authenticated ITSM
webhook. Alertmanager clustering is disabled (single replica); silences persist in
`alertmanager-data`.

#### External Prometheus (one-time installation)

An external Prometheus uses the same discovery and rule contract; ITSM never requires
remote write or engine-specific plugins.

1. Install `deploy/prometheus.yml` as a base or merge its jobs into the existing config:
   the `itsm-monitoring` config scrape, one HTTP SD job per check type, exporter
   self-scrape, and the SNMP job at `/snmp`. Replace `backend:8000` with the ITSM backend
   address reachable from the Prometheus host and `blackbox-exporter:9115` /
   `snmp-exporter:9116` with addresses routable from that host.
2. Mount the discovery token where `credentials_file` points and set the same value in
   `ITSM_MONITORING_DISCOVERY_TOKEN` for the API. Do not inline the token in YAML.
3. Install `deploy/prometheus-rules.yml` into `rule_files` once and reload configuration.
   Later asset/threshold/preset changes are read from ITSM series; this file does not
   change per device.
4. Point `ITSM_PROMETHEUS_URL` at the engine API, with `ITSM_PROMETHEUS_TOKEN` when the
   API is authenticated. Keep the engine API private; do not expose TSDB endpoints
   publicly, and use TLS at your reverse proxy.
5. If an exporter for a check type runs elsewhere, set that installation's
   `exporter_address` in ITSM so discovery overrides the scrape address while the asset
   target remains the probed destination.

#### Exporters on monitored hosts

- Linux servers: run `node_exporter` natively under the host service manager, expose
  `:9100` only to the Prometheus engine, and register the asset with `checkType: node`
  and target `host:9100`. The `monitoring-node` profile is for the Docker host itself.
- Windows servers: install `windows_exporter` as a native Windows service from its MSI,
  expose `:9182` only to the engine, and register `checkType: windows` with target
  `host:9182`. Never install a Linux node exporter service on Windows.
- DNS: register the asset with `checkType: dns` and the resolver address (`host:53`)
  as target. The question name/type is fixed in the shared module `dns_udp` in
  `deploy/blackbox.yml` (default `example.com` A); replace it once for internal zones.
  It is not configurable per device and never creates a per-asset file.
- SNMP: one shared SNMP exporter serves many devices. Credentials exist only in its
  `auths` document, never in ITSM, API responses, logs or Git; ITSM stores only the auth
  reference name per asset. Supply the document through the external environment as
  `ITSM_SNMP_AUTHS`; Compose projects it as a secret file and passes it to the exporter
  as a second `--config.file`. The committed `deploy/snmp.yml` contains modules only and
  ships no auths or default community, so the profile cannot start without the
  environment value and never probes with an empty or public credential. Example
  document shape, values supplied externally and never committed:

  ```yaml
  auths:
    switch-core:
      version: 2
      community: <community>
  ```

  Use SNMPv2c or v3 USM per device capability. Never a shared default public community.
  The fixed SNMP job selects `/snmp`, the module from ITSM (default `if_mib`) and the
  auth reference only when configured; availability is `up`, and an exporter outage is
  excluded from device-down evaluation.

No per-device manual Prometheus file is required or supported. Hosts that cannot run an
exporter are configured with ICMP/TCP/HTTP checks or left unmonitored.

#### Notification delivery

Delivery uses the internal Apprise adapter and the existing Huey worker. Channels are
configured in ITSM; each external channel stores a secret reference, never the URL/token.
`ITSM_MONITORING_SECRETS` maps those references to full Apprise URLs supplied externally:

```text
{"<channel-reference>":"<full-apprise-url-or-token>"}
```

The internal channel needs no external credential. SMTP and Telegram are external
channels; additional Apprise kinds are optional. Responses expose only whether a reference
is configured, and logs/errors redact URLs, passwords and tokens. Test channels
deliberately; do not send real external notifications without authorization.

Delivery is durable: a SQL outbox keyed by alert cycle, rule, recipient, channel and
escalation bucket feeds the queue by stable SQL id, so retries and competing workers do
not duplicate a notification. Only confirmed failures retry; ambiguous delivery remains
marked uncertain instead of being reported as success or duplicated. Delivered and failed
records, inbox entries and read state follow `ITSM_NOTIFICATION_RETENTION_DAYS`. No metric
samples are stored in SQL, and there is no second scheduler: delivery and polling reuse
the existing worker schedule.

#### Monitoring troubleshooting

- Prometheus at `http://127.0.0.1:19090` shows discovery errors on its Targets page; a
  401/403 means the discovery token differs between the engine and the API, not a
  monitoring outage. An empty HTTP SD response is correct when no asset of that check
  type is enabled.
- `probe_success` drives ICMP/HTTP/TCP/DNS; `up` drives node/windows/SNMP. Missing series
  is `no_data`, never `down`; engine errors and absent samples are not converted into
  device-down events. SNMP device-down rules are gated on the exporter self-scrape, so an
  exporter outage is not reported as every switch down.
- Alerts fire only for the target's own duration preset (0/60/300/900 seconds); the
  `preset` label shows which rule matched. A disabled or threshold-less asset has no
  configuration series, so threshold rules stay silent.
- Native Alertmanager mode is selected solely by `ITSM_ALERTMANAGER_URL`. Silences then
  exist only in Alertmanager (`/api/v2/silences`, UI at loopback `19093`), and ITSM keeps
  no duplicate local suppression. Without the URL, alerts are polled through the existing
  Huey schedule and suppression applies to notifications only.
- Engine connection failure surfaces as `unavailable` monitoring state; inventory, asset
  sheets and configuration remain usable. Do not record outages from your own failed
  queries. Periods are UTC and bounded (24h/7d/30d, at most 300 points per series);
  provenance is the engine plus the queried period.

Meilisearch's profile reserves infrastructure only; basic inventory search uses SQLAlchemy
through an internal search interface. Casbin evaluates policies from owned SQL storage.
Phase 8 implements Apprise delivery through the internal notification adapter described
above. Phase 9 uses WeasyPrint for PDFs and Segno for QR codes in the same API/worker
image; advanced search remains deferred. Pydantic AI and FastMCP reuse the canonical
business services rather than separate implementations.

### Reports, QR codes and labels

Reports use the existing Huey worker and shared `attachment-data` volume. Apply the
explicit migration before starting the API and worker; never migrate on every process
startup. Generated-document metadata is SQL-backed; PDF/CSV/Excel bytes use opaque blob
keys, not asset columns or a public static directory. API and worker must use identical
report configuration and the same blob volume.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ITSM_REPORT_BASE_URL` | `http://localhost:18080` | Frontend origin/deployment path encoded in permanent-UUID report QR links; no credentials, query or fragment. |
| `ITSM_REPORT_RETENTION_DAYS` | `7` | Generated-document retention, from 1 to 3650 days. |
| `ITSM_REPORT_MAX_ASSETS` | `1000` | Maximum matching asset selection per job, from 1 to 10000. |
| `ITSM_REPORT_MAX_DOCUMENT_BYTES` | `52428800` | Maximum output bytes per document, at most 200 MiB. |
| `ITSM_REPORT_RENDER_TIMEOUT_SECONDS` | `120` | Isolated PDF-render timeout, from 1 to 600 seconds. |
| `ITSM_REPORT_RENDER_MEMORY_MB` | `512` | PDF child-process address-space limit, from 64 to 4096 MiB. |

The image installs the required Pango/HarfBuzz libraries and DejaVu fonts. Rendering
needs no additional server and accepts only structured, allowlisted templates and
application-owned resources; never expose a filesystem directory or arbitrary resource
fetcher to make an image appear. Configure branding through the authorized report
settings rather than changing generated HTML. Missing branding uses generic templates.
Keep the report base URL stable: previously printed QR codes retain their encoded URL.
Changing an asset's site, category or quick code does not change its UUID report route.

Private reports require current `assets.view` authority and generated-document
ownership (or administrator authority). Public sharing is separate: only explicit
`reports.share` authority can issue or revoke limited-field expiring links. An asset
UUID or QR code is not a permission grant. Public output excludes technical details,
IP addresses, people, costs and attachments. Do not publish a private download URL.

### Conversation and selected MCP tools

Supply `ITSM_AGENT_MODEL` and the selected provider credential through the external
environment, then recreate the backend intentionally. No configured model means a truthful
503 from `/api/v1/agent/chat`, not fake conversational success. List/detail/CRUD/search
remain usable. Simple operations are direct; the Huey worker is not mandatory for each
tool call. This phase adds no shell, raw SQL, arbitrary URL-fetch or OS tools.

The existing backend mounts streamable HTTP MCP at `/api/v1/mcp`; no extra MCP container
or whole-REST-API export is needed. Use an explicitly installed machine identity/token
from the F2 installer, with only the required asset permissions; human session cookies do
not authenticate MCP. Configure Hermes or another compatible client with that URL and
an external `Authorization: Bearer …` header. Never put the token into chat, a URL query,
tool arguments or repository files. Revocation and Casbin checks remain backend authority.
Selected inventory tools include `search_assets`, `get_asset`, `create_asset`,
`update_asset` and bounded `batch_update_assets`. Document tools are
`list_report_templates`, `prepare_report`, `generate_report`, `report_job_status`,
`report_documents` and `generate_labels`. Their structured requests use canonical
filters and UUIDs; heavy generation returns a durable Huey job, while preparation
returns a compact authorized projection. Document references are protected API
downloads, never public filesystem paths. Audit links operations to the actor, not
a model-supplied identity. Live third-party provider/Hermes behavior is separate
from scripted-model and actual MCP protocol evidence; consult the phase record
before claiming either verified.

### Maintenance reminder preparation

Phase 7 adds persisted preventive plans, interventions and technical incidents. Apply
migrations explicitly before API/worker startup. The original Vue maintenance screens
use these APIs. Phase 8 links monitoring events to incidents, but acknowledgement,
recovery and closure stay separate: acknowledgement never resolves, recovery never
auto-closes an incident, and closing remains an explicit human decision with an
assisted-close suggestion.

The existing Huey consumer registers `maintenance_due_scan` every five minutes. Keep
one periodic scheduler per queue. Each scan reads active, non-archived plans due within
30 days, including overdue plans, and prepares one SQL reminder per plan, due date
and stage (`upcoming` or `overdue`). Durable uniqueness makes retries and competing
scans idempotent. Queue retry settings remain `ITSM_TASK_RETRIES` and
`ITSM_TASK_RETRY_DELAY_SECONDS`; no additional service or secret is needed.

Observe the structured worker event `maintenance.reminders_prepared` and its `created`
and `scanned` counters. Preparation never completes a plan, resolves an incident or
sends email/Telegram. Delivery is owned by the Phase 8 notification service described
above; the maintenance scan only prepares durable reminder rows.
See `backend/docs/maintenance.md`, `backend/docs/interventions.md` and
`backend/docs/agent-tools.md` for operation and permission contracts.

## Upgrade and rollback

1. Record all three Git revisions, component versions and image digests. Back up main DB and queue before schema/library changes.
2. Review release/security notes, update related pinned dependencies/base image digest, rebuild and run adapter/API/worker/migration tests in isolated state.
3. Test migrations against available SQL engines; do not advertise untested engines as verified. Apply a maintenance window when schema changes are not backward-compatible.
4. Run migrations explicitly, then recreate API/worker together using the tested image. Check readiness and demo task/result.
5. Keep prior image/lock. Reverting the image does not undo an irreversible migration; recover the backup if the migration cannot be safely reversed. Never run `downgrade` or restore into live data without an explicit recovery decision.

Images use exact version tags and registry digests, not `latest`. Dependencies are pinned by the backend lock and frontend package lock. No automatic updater, orchestrator, release pipeline or business microservices are required.

## Backups and recovery

- PostgreSQL: run `pg_dump -Fc` using your approved credentials to a protected destination. Check `pg_restore --list`, then rehearse restoration to a fresh database and run migrations/readiness. External database backups belong to the external operator; local Docker volumes are not backups.
- SQLite main DB: use SQLite's online backup API/`.backup`, not a casual copy of a live WAL database. For a cold file backup, stop the owned API/worker first and include a consistent database/WAL state.
- Huey SQLite: pause this workspace's API enqueue/worker, back up the entire queue volume consistently; restoring it may replay jobs. Phase 6 jobs use durable per-row receipts in main SQL to avoid replaying successful rows. Do not restore queue state independently of related business data without considering duplicate effects.
- Attachments: back up `attachment-data` together with a consistent main SQL snapshot. SQL stores metadata and opaque blob keys, not file bytes. Restoring only SQL or only the volume is incomplete. Coordinate uploads/deletions during backup and rehearse authenticated downloads after restoring to isolated state. Do not delete unknown blobs as an improvised cleanup operation; interrupted writes may leave unreferenced objects requiring an explicitly authorized reconciliation.
- Optional Redis: persist AOF and back up consistently using Redis procedures. Prometheus: back up its owned `prometheus-data` volume cold (stop the service or snapshot the filesystem) or use its supported TSDB procedure; retention is not a backup. Alertmanager state (silences and notification log) lives in `alertmanager-data`; back it up separately. Notification outbox, inbox and delivery history live in main SQL and follow the SQL backup procedure. Restoring metrics or Alertmanager state is independent of inventory availability.
- Back up root/frontend/backend repositories separately, external settings and named volumes. Never commit backup files or secrets.
- Rehearse recovery in a new isolated Compose project/volumes before replacing production. No backup/restore against existing server services is performed by this phase.

## Checks and inspection

```bash
docker compose --env-file /dev/null config --quiet
docker compose --env-file /dev/null --profile monitoring config --quiet
# Prometheus config/rules; point the token mount at the same external file the engine uses.
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/deploy/prometheus-rules.yml:/etc/prometheus/rules/itsm-rules.yml:ro" \
  -v /path/to/discovery-token:/run/secrets/monitoring_discovery_token:ro \
  --entrypoint promtool \
  prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0 \
  check config /etc/prometheus/prometheus.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/prometheus-rules.yml:/rules.yml:ro" \
  --entrypoint promtool \
  prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0 \
  check rules /rules.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro" \
  prom/blackbox-exporter:v0.29.1@sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13 \
  --config.check --config.file=/etc/blackbox_exporter/blackbox.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/snmp.yml:/etc/snmp_exporter/snmp.yml:ro" \
  -v /path/to/projected-auths.yml:/run/secrets/snmp_auths.yml:ro \
  prom/snmp-exporter:v0.30.1@sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859 \
  --config.file=/etc/snmp_exporter/snmp.yml \
  --config.file=/run/secrets/snmp_auths.yml --dry-run
# The auths file above is the content of ITSM_SNMP_AUTHS, materialized only for this
# disposable check; alternatively run the same --dry-run inside the running profile so
# the secret is already projected at /run/secrets/snmp_auths.yml.
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
  -v /path/to/ingest-token:/run/secrets/monitoring_ingest_token:ro \
  --entrypoint amtool \
  prom/alertmanager:v0.34.1@sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a \
  check-config /etc/alertmanager/alertmanager.yml
# Discovery and configuration metrics use the bearer the engine mounts; never print it.
curl -fsS -H "Authorization: Bearer $ITSM_MONITORING_DISCOVERY_TOKEN" \
  "http://127.0.0.1:18000/api/v1/monitoring/discovery?check_type=http"
curl -fsS -H "Authorization: Bearer $ITSM_MONITORING_DISCOVERY_TOKEN" \
  http://127.0.0.1:18000/api/v1/monitoring/prometheus-metrics
# Effective target schedule; discoveredLabels keep the per-job defaults.
curl -fsS http://127.0.0.1:19090/api/v1/targets | python3 -c \
  'import json,sys; [print(t["labels"].get("asset_id"), t["scrapeInterval"], t["scrapeTimeout"]) for t in json.load(sys.stdin)["data"]["activeTargets"]]'
curl -fsS http://127.0.0.1:19090/-/ready
curl -fsS http://127.0.0.1:19093/-/ready
curl --fail http://127.0.0.1:18000/api/v1/health/live
curl --fail http://127.0.0.1:18000/api/v1/health/ready
docker compose --env-file /dev/null ps
docker compose --env-file /dev/null logs --tail=100 backend worker
npm --prefix frontend run check
# Opt-in cold-start regression: isolated PostgreSQL projects, both startup orders.
# Creates volumes, stops its containers, does not delete volumes or touch other services.
python3 tests/worker_cold_start.py
# With an isolated, migrated stack and worker running:
# Requires an isolated installed account via ITSM_TEST_USERNAME / ITSM_TEST_PASSWORD.
ITSM_TEST_API_URL=http://127.0.0.1:18000 python3 tests/infrastructure.py
# Isolated SQLite inventory smoke: creates uniquely named test assets, never deletes.
# Optional ITSM_TEST_EXPECT_AGENT_UNAVAILABLE=1 checks the no-model 503 path.
ITSM_TEST_API_URL=http://127.0.0.1:18080 python3 tests/inventory.py
```

Backend tests and integration evidence are documented in backend/README.md and `odd/tasks/phase-1.md`. Demo task submission is development-only, not a public unauthenticated task-execution service. Bind loopback and require a proper authorization boundary before exposing real business data/actions. No automatic schema migration on health checks and no sensitive URL/secret values in logs or errors.

To stop only this stack, use its explicit Compose project and `down` **without `--volumes`**. Persistent-volume deletion, changing existing services and production deployment require separate authorization.

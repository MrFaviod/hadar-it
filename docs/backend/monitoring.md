# Monitoring, alerts and maintenance windows

Phase 8 adds read-only device monitoring on top of the inventory. Prometheus and
Alertmanager remain the source of truth for checks: this module discovers assets,
serves bounded read models, records alert lifecycle and links it to canonical
incidents and notifications. It does not evaluate checks or compete with
Prometheus rules.

Reads are pure. Device lists, device detail, configuration and alert reads never
materialize monitoring rows, history or audit entries. Rows are written only by
explicit configuration, alert ingestion, acknowledgement, silence, window or
incident-link commands.

## Configuration and defaults

Profiles are inherited defaults keyed by inventory category. Non-infrastructure
categories are disabled; infrastructure categories (servers, switches, routers,
UPS, cameras, containers, etc.) default to `icmp` or `snmp` checks with a
60-second interval and no latency threshold.

An asset override stores only supplied fields. Clearing a field (`null`)
removes that override and restores the profile value; clearing every field
deletes the override row. `checkType`, target syntax, exporter kind, intervals,
minimum durations, metrics and thresholds are validated before any change.
Node, Windows and TCP targets require a port. HTTP targets must be absolute
`http(s)` URLs without credentials or fragments. Unknown assets and unsupported
fields are rejected without writing domain state.

`GET /api/v1/monitoring/config` returns the effective profiles, catalog presets
and configured exporters. `PATCH /api/v1/monitoring/assets/{assetId}` edits the
asset override and `PUT /api/v1/monitoring/profiles/{category}` edits a profile.
Profiles require `config.categories`; exporter configuration requires
`config.integrations`; all other monitoring reads require `assets.view` and
every human mutation requires `assets.edit`.

## Device states

Device status is one of:

| State | Meaning |
| --- | --- |
| `unmonitored` | The effective profile is disabled. |
| `no_data` | Monitoring is enabled but no trustworthy sample exists; `reason` is `target_missing` when no valid target can be derived. |
| `unavailable` | Prometheus cannot answer; `reason` distinguishes `prometheus_not_configured` from `prometheus_unavailable`. |
| `up` | The current check succeeded and no threshold is crossed. |
| `degraded` | The check is up but a latency or metric threshold is crossed. |
| `down` | The current check failed. |

A Prometheus connection failure is never converted into device failures: every
affected device reports `unavailable`, with no synthesized alerts or history.

`GET /api/v1/monitoring/devices` returns bounded, batched list items
(`assetId`, `quickCode`, `name`, `category`, site, status/reason, check type and
target, interval, last check, latency, uptime, active alerts and severity).
Uptime is always an object `{percent, samples}`; samples can be zero and percent
can be null. `GET /api/v1/monitoring/devices/{assetId}?period=24h|7d|30d`
adds effective configuration provenance (profile/override fields, period and
step), latency aggregate, bounded metric series, checks and alert history.

Metric series are capped at 60 points and the fixed PromQL catalog only accepts
the asset UUID from the request. Supported metrics are latency (probe checks),
CPU, memory and disk (node/Windows), and temperature (node). Missing series are
empty lists, never invented values.

## Alerts

Alertmanager mode consumes standard v4 webhooks at
`POST /api/v1/monitoring/alertmanager`, authenticated by
`monitoring_ingest_token`. The body is bounded to 1 MiB and 500 alerts; the
version, labels, annotations, status, start time and asset UUID are validated
before any write. Mixed valid/invalid payloads write nothing.

Native fingerprint plus `startsAt` is the cycle identity. Repeated and concurrent
deliveries use the existing transaction-bound SQL write mutex and are idempotent;
recurrences create a new cycle, and stale resolutions only close their own older
cycle. Database errors unrelated to duplication still fail the transaction. An
unknown or mismatched `asset_id` is rejected; the inventory is never extended
implicitly. Alert detail and history are available at
`GET /api/v1/monitoring/alerts/{id}` and `/history`; human acknowledgement at
`POST .../acknowledge` preserves the firing state.

Local acknowledgement never resolves an alert. A resolved linked alert keeps
its incident open and exposes an assisted-close suggestion in the alert DTO;
the existing incident prepare/confirm workflow remains the only authority that
closes an incident. `POST .../incident` creates a minimal incident through the
canonical intervention service or links an existing one, using one non-committing
seam so an incident and its alert link share one terminal audit commit.

Temporary silences target exactly one alert (`alertId`) or one asset
(`assetId`) and require `endsAt` and a comment. Local windows suppress
notification eligibility; they do not change alert state. New firing messages
inside a silence or window are not queued or replayed after expiry. Acknowledgement
and recovery always reach the notification lifecycle, including while silenced.
Already-queued delivery and escalation re-evaluate the same monitoring
silence/window rules at processing time: active suppression pauses pending work
without spending delivery attempts. Expiry permits only still-active,
unacknowledged work to resume. Already-delivered internal inbox rows remain visible.

## Maintenance windows

A recurring window is `name`, optional `assetIds`, `daysOfWeek` (0=Monday),
`startTime`/`endTime` in `HH:MM`, an IANA timezone and `enabled`. Overlapping or
duplicate days and assets are normalized; invalid zones, times, days or unknown
assets are rejected.

When `alertmanager_url` is configured, each actual window occurrence gets one
native Alertmanager silence. Edits that change the schedule delete and recreate
that silence; a failed Alertmanager request leaves the window visible as
`alertmanagerSync: pending` and the next worker tick retries it. Without
Alertmanager, windows suppress local notifications only.

`GET/POST /api/v1/monitoring/windows` and
`PUT /api/v1/monitoring/windows/{id}` expose the CRUD surface. The alert
maintenance endpoint only prepares a suggested window; it never writes one.

## Worker and machine discovery

The Huey task `itsm.monitoring.scheduler.sync_from_prometheus` runs one bounded
sync. With `alertmanager_url` present it synchronizes maintenance-window
silences and never polls alerts (they arrive by webhook); without it, it polls
native Prometheus alerts and maintains local temporary suppression. A source
failure is logged and retried next tick, returning `unavailable` in native mode
instead of raising uncaught errors. Alert notifications are produced by an
injected flush-only notifier with stable event keys
`{alertId}:{startsAt}:{eventType}`; the notification module owns outbox
transaction and delivery.

Machine surfaces use dedicated bearer tokens:

- `GET /api/v1/monitoring/discovery?check_type=...` returns Prometheus HTTP SD
  entries with `asset_id`, check type, target, interval and labels.
  `monitoring_discovery_token` is required.
- `GET /api/v1/monitoring/prometheus-metrics` returns bounded gauges for enabled
  checks, duration presets, intervals and effective thresholds. The same
  discovery token is required.
- `POST /api/v1/monitoring/alertmanager` uses `monitoring_ingest_token`.

Deployment configuration lives in the environment, not in this module:
`prometheus_url`, optional `prometheus_token`, `alertmanager_url`, optional
`alertmanager_token`, `monitoring_ingest_token`, `monitoring_discovery_token`,
`monitoring_public_url`, `monitoring_poll_seconds` and
`monitoring_http_timeout_seconds`. `monitoring_public_url` builds canonical
inbox links (`/#/supervision/alerta/{id}`).

## Storage

Migration `0016_monitoring` stores profiles, asset overrides, exporters,
alerts/events, silences and maintenance windows. Asset deletion purges monitoring
configuration and silences but preserves alert history as readable, unlinked
records; monitoring never purges canonical inventory or incident history.

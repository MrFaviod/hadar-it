# Operations dashboard and workspace

The dashboard is a read projection over canonical modules. It never falls back
to demo data: absent Prometheus telemetry is reported as `unknown`, and every
total comes from its own aggregate query rather than from a page of rows.

## Dashboard service

`itsm.dashboard.service.DashboardService(session, identity, settings, source="api")`

- `summary(principal, period="24h", category=None, site_id=None)` requires
  `assets.view` and accepts only `24h`, `7d` or `30d`.
- Device status, uptime and latency come from
  `MonitoringService.dashboard_devices`, which reads every scoped non-archived
  asset in bounded chunks (`MAX_DEVICES`) through the existing fixed PromQL
  adapter. Each requested period trend is the weighted aggregate of the same
  availability query; no point is synthesized when Prometheus is absent.
- Active alerts, alert lifecycle activity, incidents, maintenance plans,
  warranties, inventory history and counts are read from their canonical tables
  with the same `category`/`siteId` scope filters. Detail lists are independently
  bounded; counters are separate `COUNT` queries.
- No identity/security audit is exposed; activity is inventory history plus
  monitoring alert events, with no actor usernames.
- Workstations with monitoring disabled stay in installation totals but are
  excluded from the priority device rows, matching the dashboard policy that
  workstations appear only when enabled.

Summary DTO:

```text
{
  generatedAt, period, category, siteId,
  stats: {total, monitored, up, degraded, down, unmonitored, unknown,
          criticalAlerts, unacknowledged, activeIncidents},
  availability: {configured, current, samplesCount, lastCheckAt,
                 samples: [{label, value}]},      # 24h, 7d, 30d
  latency: {current},
  distribution: [{id, label, count}],
  severity: [{id, label, count}],
  byCategory: [{id, label, total, up, degraded, down, other}],
  bySite: [{id, label, total, up, degraded, down, other}],
  activeAlerts: [{id, title, description, severity, assetId, assetName,
                  assetCode, state, acknowledged, createdAt, acknowledgedAt,
                  target: {kind: "alert", id}}],
  incidents: [{id, title, assetId, assetName, assetCode, severity, status,
               openedAt, target: {kind: "incident", id}}],
  rows: [{assetId, quickCode, name, category, type, siteId, site, status,
          reason, monitored, uptimePct, latencyMs, lastCheckAt, activeAlerts}],
  activity: [{id, at, kind, title, detail, assetId, assetName, assetCode,
              target}],
  maintenance: [{planId, assetId, assetName, assetCode, label, status,
                 statusTone, dueAt}],
  warranties: [{assetId, assetName, assetCode, until, days, coverage}],
  inventory: {total, active, unassigned,
              attention: [{assetId, assetName, assetCode, status}]}
}
```

Maximum detail sizes: alerts 20, incidents 10, rows 50, activity 15,
maintenance 10, warranties 10, inventory attention 10.

## Workspace state

`itsm.workspace.service.WorkspaceService(session, identity, source="api")`

- Personal preferences are keyed by the authenticated `actor_id`; reads never
  create rows.
- `get_state(principal)` always returns
  `{widgets, favorites, usage, lastViews, themeMode, shortcuts, views}`.
  A missing row yields the existing eight widget defaults; an explicit empty
  `widgets` list means every widget is hidden. `themeMode` defaults to `auto`.
- `save_state(principal, payload)` is a top-level partial patch for
  `widgets`, `favorites`, `usage`, `lastViews` and `themeMode`; omitted keys are
  unchanged and unknown keys are rejected.
- Valid widget ids: `availability`, `alerts`, `distribution`, `infrastructure`,
  `activity`, `maintenance`, `warranties`, `inventory`, plus optional `latency`
  and `incidents`. Temporary additions remain client-session state and never
  overwrite the durable layout.

State DTO:

```text
{
  widgets: [id],
  favorites: [{key, type, id, label, subtitle, icon, target}],
  usage: {key: count},
  lastViews: {route: snapshot},
  themeMode: "light" | "dark" | "auto",
  shortcuts: [...]  # visible personal + shared
  views: [...]      # visible personal + shared
}
```

## Shortcuts, views and integrations

`create_dashboard_router()` mounts all routes under `settings.api_prefix`:

| Route | Permission |
| --- | --- |
| `GET /dashboard?period&category&siteId` | `assets.view` |
| `GET|PUT /workspace/state` | authenticated |
| `GET|POST /workspace/shortcuts` | authenticated; shared create/update requires `config.general` |
| `PATCH|DELETE /workspace/shortcuts/{id}` | owner only; shared row additionally requires `config.general` |
| `GET|POST /workspace/views` | authenticated; shared create requires `config.general` |
| `PATCH|DELETE /workspace/views/{id}` | personal owner only; publishing a view requires `config.general` |
| `GET /workspace/integrations` | `assets.remote` (canonical sensitive check) or `config.integrations` |
| `PUT /workspace/integrations` | `config.integrations` |

Shortcut DTO: `{id, name, url, icon, category, scope, ownerId}`. View DTO:
`{id, name, route, snapshot, scope, ownerId}`. The owner is always the actor id
from the authenticated principal, never a client field. Personal rows are
invisible to other accounts (`404`); shared rows are visible to every
authenticated account and only their owner can modify them. External links are
plain `http(s)` URLs with no credentials, control characters or host-only
targets. View routes and snapshots are bounded JSON; snapshots are capped at
8 KiB and 5 levels.

Integrations DTO:
`{anydeskUrl, rmmUrl, anydeskEnabled, rmmEnabled}`. The installation singleton
defaults to `https://anydesk.com/`, empty RMM URL and both flags enabled. `PUT`
is a partial merge; URLs must be `http(s)` without credentials, at most 500
characters, and may be empty when the provider is disabled. Per-asset AnyDesk
and Tactical RMM identifiers stay in the canonical asset record and are never
stored here.

## Persistence

`itsm.workspace.models` (all on `InventoryBase`, no foreign keys):

| Table | Columns |
| --- | --- |
| `workspace_user_state` | `user_id` String(36) PK, `widgets`/`favorites`/`usage`/`last_views` JSON nullable, `theme_mode` String(16) default `auto`, `updated_at` |
| `workspace_shortcuts` | `id` String(36) PK, `owner_id` String(36), `name` String(120), `url` String(1000), `icon` String(64), `category` String(64), `scope` String(16) default `personal`, timestamps; index `(owner_id, scope)` |
| `workspace_views` | `id` String(36) PK, `owner_id` String(36), `name` String(120), `route` String(128), `snapshot` JSON, `scope` String(16) default `personal`, timestamps; index `(owner_id, scope)` |
| `workspace_integrations` | `id` String(16) PK, `anydesk_url`/`rmm_url` String(500), `anydesk_enabled`/`rmm_enabled` Boolean default true, `updated_at` |

Schema changes are managed through the application migration chain.

## Composition

`create_dashboard_router()` returns a plain `APIRouter`; the application mounts
it before the MCP mount:

```python
from itsm.dashboard.api import create_dashboard_router
api.include_router(create_dashboard_router())
```

No settings or task queue changes are required. Frontend hydration of the
branding/integration values uses the same response fields already mapped by the
original configuration store.

## Client restoration boundary

Shortcut DTOs are revalidated with the existing HTTP(S)/no-credentials normalizer before hydration and after shortcut writes. Invalid links are not rendered; shared-link visibility does not grant edit ownership. Snapshot restoration copies only own fields in each view's existing `workspaceFields`. Inventory accepts only captured prefs/filter/status/location/selection fields. It does not assign methods, component controls, arbitrary root preferences or inherited fields, and does not deep-merge nested objects. Saved map/graph layouts and live shared explorer filters retain their previous precedence.

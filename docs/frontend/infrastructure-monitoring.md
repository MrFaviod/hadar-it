# Infrastructure monitoring on the canvases

Scope: the map and the relationship graph show the availability the monitoring
module publishes, joined to the canvas by canonical `assetId`.
Administrative inventory status stays a separate fact and is not
rewritten from telemetry.

The interface uses existing backend endpoints, policies and permissions: the
frontend reads `GET /api/v1/monitoring/devices` and
`GET /api/v1/monitoring/devices/{assetId}`, both guarded by the existing
`assets.view` permission, and renders what they already return.

## What is shown, and what is not

The join lives in `assets/js/infrastructure-monitoring.js` (an application
mixin, `window.AssetInfrastructureMonitoring`, loaded by `index.html` before
`graph-views.js`). Both canvases read the same state, so the map and the graph
can never disagree.

- One bounded page read: `limit=200`, `offset=0`, `period=24h`. The canvas
  never issues one request per asset.
- Rows are matched to the loaded canvas by `assetId`. An asset the page did not
  return keeps **no availability claim**: no badge, no uptime, and an explicit
  "No reading for this asset" note instead of an invented state.
- The coverage line states what was examined against the server total
  (`Monitoring {examined} of {total}`), so a bounded page is never presented as
  the whole inventory.
- Inventory status (`in_use`, `assigned`, …) and measured availability
  (`up`/`degraded`/`down`) are different facts and are labelled as such.
- Only measured, actionable states produce a canvas badge: `down` and
  `degraded` (with the active-alert count when there is one). `up`, `no_data`,
  `unmonitored` and `unavailable` paint nothing, because they are not an alert.

## Rendering

- **Graph** (`assets/js/graph-views.js`): a `.gnode__state` disc opposite the
  existing "more" badge, warning for degraded and danger for down, carrying the
  active-alert count or `!`. The node's accessible name appends the measured
  state, so the plate is not colour-only.
- **Inspectors**: one `.infra-monitor` block on both surfaces (styled in
  `graph.css`, which loads on every route). It shows the state pill, the reason when the API publishes one, and the
  read failure with `role="alert"` directly under the pill, so a failed refresh
  is the first thing read rather than the last. Below that: uptime, the last
  check, active alerts, latency, the most recent alerts, and the coverage and
  freshness note.
- Manual refresh is `[data-od-id="graph-monitor-refresh"]` /
  `[data-od-id="map-monitor-refresh"]`: `aria-busy` while reading, disabled to
  prevent a second in-flight read, and it re-reads the list and the selected
  device.

## Honest states

| Monitoring answer | Canvas | Inspector |
|---|---|---|
| `down`, `degraded` | danger / warning badge (alert count) | pill, uptime, last check, alerts, latency |
| `up` | no badge | pill, uptime, last check, latency |
| `unmonitored` | no badge | pill only: no checks are configured, so there is nothing to paint |
| `unavailable` | no badge | pill plus the published reason (`No reading`) |
| `no_data` / `null` | no badge | pill only |
| row absent from the page | no badge | "No reading for this asset" plus coverage |
| detail `404` | unchanged | falls back to the current list row and drops the earlier reading; not an error |
| list read fails (`5xx`, network) | previous badges kept | error message plus the last good reading, and the refresh stays retryable |
| device read fails after a good reading | previous badges kept | last good reading kept, the failure reported under the pill, refresh stays enabled |

A failed read never replaces the last good state with zeros and never presents
the previous device's reading: the detail carries an asset id and is only
painted for that id. A page read that fails cannot leave a device marked as
loading, because that would disable the refresh control and lock every retry.

Labels are resolved from the neutral status and reason codes at render time,
not stored with the reading: switching language relabels the block and the
canvas announcement without another transport read.

## Lifecycle

- One timer, `REFRESH_MS = 60s`, scheduled after each completed read. It never
  overlaps: a read in flight suppresses the next one, and the timer handle is
  released (`unref`) where the runtime supports it.
- Reads are guarded by a monotonic generation (`epoch`) plus a per-detail
  request counter, so a late answer from a previous generation, or from a
  previous selection of the **same** asset (A → B → A), cannot repaint the
  current selection.
- Identity: `app.activeUserId` and `app.authenticated` are watched. Logging out
  or unmounting disposes the state, aborts both controllers and advances the
  generation — the epoch never resets to `0`, so a discarded answer cannot
  collide with a new generation. Replacing the signed-in person with another
  non-empty id also disposes and reads again.
- A session restored after mount (`authenticated` flipping to `true` for a deep
  link) starts the bounded read; the canvas may mount before the session
  resolves.
- `visibilitychange` pauses the join: the timer is cleared and in-flight reads
  are aborted and discarded, so a hidden tab does not keep a stale paint.
- A selection made outside a pointer event - a deep link such as
  `#/infra/mapa/activo/<id>`, or a restored route - is read like a click, and a
  selection that changes while the page read is still open is read as soon as
  that page lands.
- A refresh asked for while any read is still open is queued, not dropped: it
  runs once when that read settles, and never twice, because the queue flag is
  cleared before the follow-up starts.
- The deep-link focus is applied only until it resolves. Once the asset is open,
  a later canonical inventory refresh replaces the asset objects and leaves the
  person's selection alone instead of snapping back to the route.
- Opening another asset, or closing the inspector, cancels the route intent:
  when the inventory finally contains the deep-linked asset it is not reopened
  over the person's choice. A route that has not been superseded still resolves
  when the asset arrives, which is what makes a cold deep link work.
- No permission is granted or assumed: `assets.view` is checked on the client
  exactly as before. This is a display guard only; the server remains the
  authority for the read.

## Copy

Nine keys were added to `assets/i18n/es.json`, `assets/i18n/en.json` and their
`context.json` notes: `ui.infra.monitor.{title, uptime, latency, unknown,
coverage, updated, not_loaded, error}`. Status and action labels reuse the
existing `ui.monitoring.*` catalog, so the canvas and the monitoring view name
the same state with the same word.

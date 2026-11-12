# Technical interventions and incidents

Technical work is kept as first-class, queryable records beside the asset
sheet. Every write goes through `InterventionService`, so the HTTP adapter,
future agent tools and machine credentials share one authorization and
validation path. Assets, directory people and attachments remain owned by their
existing modules; this module only stores canonical references.

## Records

| Table | Purpose |
| --- | --- |
| `technical_interventions` | One job on one asset: type, description, technician, date, status, notes, parts, labour cost, optional incident/plan links. |
| `technical_intervention_attachments` | Ordered references to canonical attachment UUIDs; the blob must belong to the intervention's asset. |
| `technical_incidents` | Description, priority, status, primary asset, optional responsible person, opening/resolution/closure marks, revision and resolution token. |
| `technical_incident_assets` | Unique additional affected assets, in input order. |
| `technical_incident_events` | Append-only actuation history with actor, source, statuses and structured changes. |

Interventions are individual records, so an asset can carry many jobs and one
incident can link many interventions without sharing a mutable aggregate.

## Creating minimal records

An incident needs only `primaryAssetId` and `description`; priority defaults to
`normal`, the responsible person is inherited from the primary asset, today is
the opening date, and extra affected assets are optional. An intervention needs
only `assetId`; type defaults to `corrective`, status to `open`, date to today,
and description, technician, parts, costs, attachments and links are optional.

Money is stored as a canonical two-decimal string and returned as a string.
Costs are `null` when the operator supplied none. `totalCost` is the sum of
labour and the supplied parts only, never an estimate. Dates use ISO `YYYY-MM-DD`.

## References

* Assets must exist (`404` when they do not).
* Technician and responsible people must exist in the directory and be
  `active`; a person is never an account and gains no access.
* Attachments must be live rows of the intervention's own asset. Paths and
  filenames are never accepted, and the same attachment cannot be linked twice.
* `planId` references a real preventive plan owned by the intervention asset.
  The canonical maintenance service validates it (`404` for an unknown plan,
  `422` for another asset) and completes linked preventive work atomically.
* `incidentId` must reference a non-closed incident.

## Lifecycle

Interventions: `open → in_progress → completed`, with `cancelled` reachable from
`open` or `in_progress`. Terminal statuses cannot reopen. `intervention_completed`
is recorded once, at the transition that actually completes the work.

Incidents have an explicit, ordered lifecycle and no automatic path:

| Action | Allowed from | Result |
| --- | --- | --- |
| `acknowledge` | `open` | `in_progress` |
| `resolve` | `in_progress` | `resolved` |
| `close` | `resolved` | `closed` |
| `resolution/prepare` | `open`, `in_progress` | unchanged; issues a single-use token |
| `resolution/confirm` | `open`, `in_progress` | `resolved` with a fresh token |

Connectivity recovery, connectivity monitors and automatic incident creation do
not exist in this phase. A later recovery signal may call `prepare_resolution`,
which only *suggests* resolution: it changes no status and returns a token bound
to the current incident revision. `confirm_resolution` rechecks the caller's
live Casbin `assets.edit` authority, the incident state and the stored digest;
a stale, replayed or superseded token is rejected with `409` and changes
nothing. Any mutation (status, affected assets, linked intervention) bumps the
revision and revokes a prepared token, so a stale preparation cannot resolve an
incident whose evidence changed.

## HTTP API

All routes are under the configured API prefix (`/api/v1` by default). Reads
require `assets.view`; writes require `assets.edit`. Cookie clients must send
`Origin` and `X-CSRF-Token`; machine bearers still go through Casbin.

```
POST   /interventions                            201
GET    /interventions                            filters + pagination
GET    /interventions/costs                      accumulated cost summary
GET    /interventions/{intervention_id}
PATCH  /interventions/{intervention_id}
POST   /incidents                               201
GET    /incidents                                filters + pagination
GET    /incidents/{incident_id}
PATCH  /incidents/{incident_id}/affected-assets
POST   /incidents/{incident_id}/acknowledge
POST   /incidents/{incident_id}/resolve
POST   /incidents/{incident_id}/close
POST   /incidents/{incident_id}/resolution/prepare
POST   /incidents/{incident_id}/resolution/confirm
GET    /assets/{asset_id}/technical-history
```

Filters: interventions accept `category`, `site`, `siteId`, `status`, `type`,
`assetId`, `technicianPersonId`, `incidentId`, `planId`, `from`, `to`, `limit`
and `offset`; incidents accept `active`, `status`, `priority`, `category`,
`site`, `siteId`, `assetId`, `responsiblePersonId`, `from`, `to`, `limit` and
`offset`. Costs accept the same intervention filters (including `category`,
`site`, `siteId`, `status`, `type`, `technicianPersonId`, `incidentId`,
`planId`, `assetId` and the date period) and return
`{totalCost, countedInterventions}`. Pages are bounded (`limit` 1–200, default
50) and always return `{items, total, limit, offset}`. `category`, `site` and
`siteId` filter through the asset, so they stay current with the asset sheet;
`siteId` is the canonical site UUID while `site` keeps the stored label.
Malformed site/plan UUIDs and a `from` after `to` return `422`, and period
filters compare against `occurredOn` for interventions and `openedOn` for
incidents. Costs are aggregated only from supplied amounts.

PATCH on an intervention updates details, progresses the state along the table
above, and replaces attachment references. Unlinking removes only the reference
row; the canonical blob stays owned by the attachment module and remains
downloadable. Blob deletion is blocked while a reference exists (guard owned by
the attachment module).

## History and traceability

Every business mutation appends one row to the existing asset history using the
shared `InventoryService._record_history` and the adapter's source
(`rest`, `agent`, `mcp`, `internal`). Actions:

| Action | Assets |
| --- | --- |
| `intervention_logged` | intervention asset |
| `intervention_updated` / `intervention_completed` | intervention asset |
| `incident_opened` | primary asset |
| `incident_assets_updated` | primary asset plus added/removed assets |
| `incident_acknowledged`, `incident_resolution_prepared`, `incident_resolution_confirmed`, `incident_resolved`, `incident_closed` | primary and affected assets |

Rows carry `entityType` (`intervention`/`incident`) and `entityId`, so
`GET /assets/{asset_id}/technical-history` returns only technical events in the
existing structured history shape. Incident events keep their own ordered
history with notes, actor and source.

Each mutation runs under the shared `serialized` write lock and ends with the
single terminal `IdentityService.record_operation` audit commit. Rejected input
leaves records, history and counters unchanged.

## Querying

* Pending / upcoming / overdue preventive work stays in the preventive module;
  this module exposes the recorded jobs and incident state.
* `GET /interventions/costs` returns `{totalCost, countedInterventions}` for the
  supplied asset/incident/period, or `null` when no cost was recorded.
* `GET /incidents?active=true` returns everything not yet closed.

## Integrated boundaries

* `itsm/main.py` mounts both technical and preventive routers.
* Existing `assets.view` and `assets.edit` permissions apply; no implicit grants.
* Attachment deletion rejects live intervention references before changing the
  attachment or its stored bytes.
* Permanent asset purge rejects persisted preventive plans, interventions and
  primary or affected incident references; virtual default plans do not block it.
* Linked preventive completion shares the intervention SQL transaction and audit
  commit. Only entering `completed` for preventive work advances its plan;
  corrective work and repeated completed updates leave the cycle unchanged.
  A conflicting completion rolls back the intervention and its history too.

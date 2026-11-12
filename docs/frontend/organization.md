# Directory, relationships, graph and map

How the organization screens of the interface use the canonical server API: people, departments, locations, relationships, the infrastructure graph and the site map. The UI is Vue 3 with the Options API and `index.html` templates; there are no single-file components and no domain state in React.

## Component map and contracts

| Module | Responsibility | Contract |
|---|---|---|
| `assets/js/organization-api.js` | The single organization adapter: people, departments, locations, tree, relationship types, relationships, graph, map and history. Keeps a monotonic epoch, `AbortController` and per-resource errors. | `window.AssetOrganization.{data,computed,methods,map*,canonical*}` |
| `OrganizationRelations` (`relations-views.js`) | An asset's relationship panel: directed list with forward/inverse label, create/edit/delete and host change. | props `asset`, `app`; uses `organization.relations`, `organization.types`, `organization.dialogs.*` |
| `OrganizationRelationTypes` (`relations-views.js`) | Configuration of the type vocabulary (immutable key, labels, containment, active). | permission `config.general`; routes `/relationship-types` |
| `GraphExplorer` | Reuses the existing engine and design over a proxy source bounded by the server. | `serverGraphMode`, `organizationGraphSource`, `organization.graph` |
| `MapExplorer` + `FloorLogic` | Reuses the existing floor-plan canvas; converts canvas pixels to relative 0..1 coordinates and persists positions. | `serverMapMode`, `organizationMapSource`, `saveOrganizationPosition` |
| `AssetEditor` | Replaces person/site/location selectors with the canonical UUIDs the inventory adapter already uses. | `assetSiteLocations`, `assetActivePeople`, `app.sites` |
| People page | List, record, history, assign/return/transfer with reason, notes and effective date. | `/people`, `/people/{id}`, `/people/{id}/assets`, `/people/{id}/history`, `/assets/{id}/assign|return|transfer` |

## REST contracts used

- Directory: `GET|POST /departments`, `GET|PATCH /departments/{id}`,
  `GET|POST /people`, `GET|PATCH /people/{id}`, `GET|POST /locations`,
  `GET /locations/tree?rootId&depth&maxNodes`, `GET|PATCH /locations/{id}`,
  histories `GET /{entidad}s/{id}/history`.
- Lifecycle: `GET /people/{person}/assets`,
  `POST /assets/{id}/assign`, `POST /assets/{id}/return`,
  `POST /assets/{id}/transfer`, `PATCH /assets/{id}` (canonical position).
- Relationships: `GET|POST /relationship-types`, `PATCH /relationship-types/{key}`,
  `GET|POST /relationships`, `PATCH|DELETE /relationships/{id}`,
  `POST /relationships/host-move`, `GET /infrastructure/graph`.
- Map: `GET /map?siteId&limit&offset`. The payload is
  `{sites, positions, limit, offset, truncated}`; each position carries the
  asset's canonical ids and `x`/`y` as 0..1 decimals, not `positionX`/
  `positionY` or an `items` list.

Every read validates a monotonic epoch; every write rechecks the server's
effective permission before sending. A 401 clears all organization state and
aborts in-flight requests. The server domain never writes to `localStorage`.

## Permissions

`people.view`, `people.create`, `people.edit`, `config.departments`,
`config.sites`, `assets.view`, `assets.edit`, `assets.assign`,
`config.general`. A missing capability produces a factual message and, where
appropriate, a read-only view; it is never filled with demo data.
`config.departments` without `assets.edit` manages the directory without
enabling asset editing.

Redundancy groups shown on the asset record and in the graph have their own
contract in [Redundancy groups](redundancy.md): they are read with `assets.view`,
written with `assets.edit`, and grant no new organization capabilities.

## Coordinates and floor plans

The server exposes `positionX`/`positionY` as decimal strings in 0..1. The
canvas keeps its pixel space and converts using the plan's real bounds
(`organizationPlanBounds`). A position is only sent when the asset has a
location; `planRef`/`planPage` are metadata, never a file or a plan URL. The
existing floor-plan drawing remains illustrative.

## Changing the host

`OrganizationRelations` offers **Change host** only on the child of a
`hosted_in` relationship and opens a `modal-shell` dialog with real Vue
controls: the asset changing host (its canonical name or, if the panel does not
know it, its UUID), the target search `#server-host-search`, the list of hosts
from the server's bounded page, the reason `#server-host-reason`, the notes
`#server-host-notes` and the effective date `#server-host-effective`. Confirming
calls the existing `confirmOrganizationHostMove`; closing, `Escape` and the
cancel button use `closeOrganizationHostMove`. `modal-shell` keeps focus,
returns it to the trigger and locks document scrolling.

- The child is always taken from the edge's origin (`from`), whether the
  relationship is seen as outgoing or incoming; direction only changes labels.
- The target is the server's bounded page `GET /assets/search?limit=50&offset=0`.
  The interface neither filters nor validates on its own: the server decides
  whether a host is valid and its rejection stays in the dialog. The same host,
  the asset itself or the current host are not rejected on the client.
- The server's minimum four-character reason is checked before sending, to
  avoid a predictable 422. Notes and effective date are optional; the date is
  converted with `organizationEffectiveIso` and keeps the browser time zone.
- The request is `POST /relationships/host-move` with `{childId, newHostId,
  reason, notes?, effectiveAt?}`. It includes no authority arguments and calls
  no hypervisors, Docker or migrations: it only records inventory and
  relationships.
- After success the relationships reload from the server, the graph reloads if
  it was loaded, and, when the affected asset is open on its record, so do the
  detail and structured history. Each refresh revalidates the session mark, so
  a sign-out in progress does not revive rows, dialogs or notices.
- A server rejection keeps the dialog open, leaves the message in its body and
  does not change the relationship on screen.

## Known limits

- In an authenticated session the organization domains read only from the API.
  Loading, errors and missing permissions never authorize a demo fallback or
  local persistence of the domain. Visual map preferences remain local state.
- Positions require a location and paired relative coordinates. Floor plans
  remain illustrative representations with `planRef`/`planPage`; there is no
  file storage, geocoding or discovery.
- A truncated graph may omit relationship endpoints; the UI does not invent
  nodes. A location whose ancestor chain is not loaded is not invented in search.
- The integrated test uses SQLite. It does not certify external engines, model
  providers, hypervisor integration or production.

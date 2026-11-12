# Map and graph explorer

The infrastructure explorer (**Map** and **Graph** views) keeps its original routes, templates, design tokens,
icons, keyboard behavior, light/dark themes and 390 px layout. It now reads the
canonical directory, `/map`, `/infrastructure/graph` and authenticated directory
media instead of the prototype-only map model.

## Canonical data

- `/map` remains authoritative for geographical sites and individual positions.
- `/assets/search?limit=200&offset=N` supplies the asset pool. Pages are bounded
  at 200 and followed until `total` is covered; the walk shares the map abort
  signal, so logout or a newer map load stops it. The pool enriches positioned
  assets with category, status, technical metadata and images, and keeps every
  device without individual coordinates associated with its room or floor. A
  failed secondary pool read does not hide the canonical `/map`.
- `/locations/tree` drives the site/building/floor/room hierarchy. Floor
  resolution walks the canonical ancestry, so a device assigned to a floor or
  building stays in that floor instead of falling back to the site's first floor.
- Camera field of view is the existing authenticated
  `/assets/{id}/images/fov`; the numeric angle comes from `technical.fovAngle`.
  The synthetic SVG cone was removed.

## Floor plans

The frontend reads plan metadata from `GET /api/v1/locations/{id}/plan/meta` and
the raster bytes from `GET /api/v1/locations/{id}/plan` through `AssetAccess`
(`responseType: 'blob'`, session cookie). Bytes become a revoked object URL and a
MapLibre `image` source, rendered as a raster layer over a valid synthetic
Mercator box: longitude `0..1600/1000` and latitude `0..1`, four corners. The
geographic map coordinates are untouched, and the plan aspect ratio is kept.

The plan layer supports pan/zoom, room/asset overlays projected through the
floor MapLibre instance, visibility, opacity, loading, empty (404) and retry
states. Dragging a marker inverse-projects through MapLibre and persists the
canonical position only for users with edit permission. Prototype mode keeps its
original normalized plan behavior.

The floor canvas is absolutely positioned inside the plan paper, overriding the
vendor canvas-container rule. The maximum zoom is 16 so a full-plan fit is not
clamped below the viewport's required zoom.

Assets without individual coordinates stay visible in a grouped native
`<details>` list per room or floor; they are never dropped or treated as errors.

## Graph

`GraphExplorer` now reads `assets`, `sites`, `relations`, `categories`, selected
rows and relation counts from its canonical source proxy in server mode. Opening
a node passes the canonical asset to `app.openAsset`, whose route is the original
`#/activo/{id}`. Filters, selection and the Mapa↔Grafo switch keep the existing
precedence.
Canonical focused routes retain UUID selection while asynchronous graph data
arrives. The focused node is resolved from the graph response, not the currently
loaded inventory page. Saved route state is restored before shared cross-view
filters; an empty shared filter object does not erase persisted filters.

## Backend contract

C4 adds `itsm/directory/media.py` and `media_api.py`:

- `GET /locations/{id}/plan/meta` — read permission `assets.view`, `PlanView`
  `{locationId, planRef, planPage, contentType, width, height, size, planUrl}`.
- `GET /locations/{id}/plan` — bytes with `X-Plan-Width`/`X-Plan-Height`,
  no-store and an inline filename.
- `PUT /locations/{id}/plan` — write permission `config.sites`, CSRF, raw bounded
  PNG/JPEG/WebP bytes.
- `DELETE /locations/{id}/plan` — same write authority, `204`.

Validation bounds: 5 MiB, 8192 px per side, 25 Mpx and one fully decodable raster
frame. Corrupt or truncated replacements are rejected before storing bytes.
Storage is opaque and deterministic under
`attachment_storage_path/directory-plans`; responses expose no filesystem
paths. Missing storage answers `503`. The router is mounted before the MCP mount
with prefix `/api/v1`; no migration is needed for plan metadata.

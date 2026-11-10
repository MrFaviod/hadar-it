# Infrastructure expansion

The map and relationship graph can expand into the infrastructure workspace.
Expansion changes layout, not monitoring or alert behavior.

## What "expand" is

The expanded state is an **in-app full-window layout**, not the browser
Fullscreen API. The canvas element stays mounted and only its frame changes:
the page's `map-layout`/`graph-layout` becomes a fixed region below the top bar
(`inset: var(--topbar-h) 0 0`), the location tree / filter column is hidden and
the inspector column is kept, so the selection stays readable while expanded.
Nothing is re-created, so filters, selection, camera, zoom and the running
layout objects survive by construction. A native fullscreen request would add a
permission-gated browser surface without giving users anything the in-app
workspace lacks; the layout can be entered and left without changing application authority.

## Map (`assets/js/map-views.js`, `assets/css/map.css`)

- Resting height `clamp(560px, calc(100vh - 220px), 1180px)` (was capped at
  760px); the location tree follows the same maximum so both columns stay even.
- `[data-od-id="map-expand"]` toggles `map-page.is-expanded`; `aria-pressed`
  and a translated accessible name describe both directions
  (`ui.map.aria.expand_canvas` / `ui.map.aria.collapse_canvas`).
- Enter and exit call `map.resize()` and the floor map's `resize()` on the next
  frame and once more after it. The MapLibre instance is never re-created and
  the camera is never eased or re-fitted by expanding.
- `Escape` inside the stage leaves the workspace and returns focus to the
  control; the handler is a no-op when collapsed, so it does not swallow the
  key for the rest of the page.
- The page scroll is locked with `body.map-workspace-expanded` while expanded
  and the class is removed on exit and on unmount.
- `selectSite` now reads the site geometry from the active map source
  (`this.source`) instead of the prototype application, so selecting a site in
  server map mode actually frames it.
- The stage selector is `.map-stage > .map-canvas`, not `.map-canvas`. The
  vendored `assets/vendor/maplibre-gl.css` is linked *after* `map.css` and its
  `.maplibregl-map { position: relative; overflow: hidden }` has the same
  specificity as the old rule, so it won and the container collapsed to zero
  height: MapLibre kept its 455x300 default size and the canvas painted into a
  0px box. At 1440 that read as a blank map behind the markers; below 1080 the
  media rule made the container relative again, which is why only the wide
  viewport looked broken. The two-class selector is immune to load order and
  needs no `!important`.
- The map shows administrative inventory status through the shared catalog
  (`ui.inventory.status.*`), never a device reachability claim.
- The map still shows organisation geometry and inventory status only. There is
  no reachability, latency or uptime claim on this surface.

## Graph (`assets/js/graph-views.js`, `assets/css/graph.css`)

- Resting height `clamp(560px, calc(100vh - 240px), 1180px)` (was capped at
  720px).
- `[data-od-id="graph-expand"]` toggles `graph-page.is-expanded`; the canvas
  fills the window next to its inspector.
- Expanding re-measures the mounted canvas and reheats the existing simulation.
  The simulation object is reused, the visible node/edge set is untouched and a
  queued re-fit is cancelled, so the zoom the user had is preserved exactly
  (`keepZoom`), including the extra resize reports the observer emits while the
  frame grows.
- `handleResize` anchors on the centre of the canvas *before* the change, so a
  genuine container resize (inspector opening, window resize) keeps the world
  point the user was looking at instead of the centre of the new frame.
- `Escape` leaves the workspace without clearing the selection; a second
  `Escape` in the resting layout still clears it as before.
- Selecting a node mutes plates and links that are not related to it
  (`is-dimmed`, opacity only). Relation types, direction, labels and the
  redundancy panel keep their canonical meaning; nothing is merged or inferred.
- `categoryLabel` prefers the category label the server exposes and only falls
  back to the imported prototype table for ids that predate the catalog, so a
  server category can no longer render as `Otros` (or as the wrong family).

## Administrative status in the inspectors

Both inspectors rendered the raw stored code (`in_use`). They now render the
same contract: a status the server defines keeps its own label (including
renamed and custom ids), the four built-in ids resolve through the existing
`ui.inventory.status.*` catalog entries, and an id with no catalog entry is
shown as stored rather than invented. This is administrative inventory state;
it says nothing about whether the device is online, and the map/graph do not
imply otherwise.

## Copy

Four new keys, Spanish and English, each with its `context.json` note:
`ui.map.aria.expand_canvas`, `ui.map.aria.collapse_canvas`,
`ui.graph.aria.expand_canvas`, `ui.graph.aria.collapse_canvas`. The controls are
icon-only, matching the existing canvas control groups, so no verbose visible
label was introduced.

## Family legend labels

The legend chips of both canvases read the five built-in families (`compute`,
`server`, `network`, `virtual`, `power`) from the active catalog through the new
`ui.relations.family.*` keys (Spanish and English, with their `context.json`
notes). `familyLabel` only translates a known built-in id, also when the catalog
is absent (the authored Spanish text stays readable), and an unknown family id
is shown as stored instead of being replaced by a built-in label. No server
taxonomy, migration or backend change was needed: these ids are a stable
frontend enum. Category labels inside the inspectors keep their existing
contract — the server catalog label wins and custom ids keep their own text —
so no server-provided data is mapped or renamed.

A category outside the built-in table is grouped under `compute`: the family is
a presentation hint for the legend and the swatch, not a statement about the
asset, and no family taxonomy is inferred from server data.

## Scope

Expansion only changes layout. Live availability, uptime, latency and alerts
are described in [Infrastructure monitoring](infrastructure-monitoring.md).

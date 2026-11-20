# Installation appearance

Backend contract for installation appearance and portable branding packages.
The appearance editor uses this module as its canonical, durable backend.

## Preset document

The preset schema is unchanged from the original engine. It is installation
data, not per-user data. `themeMode` stays a per-user workspace preference;
the preset only stores its default.

```json
{
  "id": "generic",
  "name": "Hadar IT",
  "version": 1,
  "description": "Identidad original · Siempre disponible",
  "branding": {
    "appName": "Hadar IT",
    "organizationName": "Operaciones TI",
    "logo": "/api/v1/appearance/assets/logo",
    "logoDark": "",
    "logoCompact": "",
    "favicon": "/api/v1/appearance/assets/favicon"
  },
  "colors": {
    "light": {"primary": "#0b2331", "secondary": "#0d766e", "accent": "#a65c13"},
    "dark": {"primary": "#071923", "secondary": "#62d4c7", "accent": "#f6bf67"}
  },
  "preferences": {"defaultMode": "system", "compact": false}
}
```

Rules:

- `version` is exactly `1`; names are 1–120 printable characters, descriptions
  up to 500.
- Six colors are lowercase `#rrggbb`.
- `defaultMode` is `light`, `dark` or `system` (`auto` normalizes to `system`
  in the user preference layer, C1).
- The four graphics are optional. An empty string means "not configured".
  Accepted references are an uploaded opaque resource URL
  (`/api/v1/appearance/resources/<32 hex>`), a built-in asset URL, the legacy
  `assets/svg/...` path for the two packaged graphics, or a base64 image data
  URL. Arbitrary paths, HTTP(S) URLs and other schemes are rejected.
- Built-ins `generic`, `blue` and `forest` are code constants and immutable.

## HTTP API

All routes are mounted under `settings.api_prefix` by the application.

| Method | Path | Access | Result |
| --- | --- | --- | --- |
| GET | `/appearance/active` | public | `{active, activeId, previousId, builtinIds}`; safe for the login shell |
| GET | `/appearance/presets` | authenticated | `{active, activeId, previousId, presets, builtinIds}` |
| POST | `/appearance/presets` | `config.general` + CSRF | `201 {preset}` |
| PUT | `/appearance/presets/{id}` | `config.general` + CSRF | `{preset}` |
| DELETE | `/appearance/presets/{id}` | `config.general` + CSRF | `204` |
| POST | `/appearance/apply/{id}` | `config.general` + CSRF | catalog envelope |
| POST | `/appearance/restore` | `config.general` + CSRF | catalog envelope; active becomes `generic` |
| POST | `/appearance/revert` | `config.general` + CSRF | catalog envelope; swaps active/previous |
| GET | `/appearance/presets/{id}/export` | `config.general` | self-contained `application/zip` |
| POST | `/appearance/import/preview` | `config.general` | parsed preview; writes nothing |
| POST | `/appearance/import` | `config.general` + CSRF | `201 {preset, staged: true}` |
| GET | `/appearance/resources/{id}` | public, opaque ID | validated graphic |
| GET | `/appearance/assets/{key}` | public | packaged `logo` / `favicon` SVG |

Authenticated JSON is `Cache-Control: no-store`. Graphics are immutable,
`nosniff`, sandboxed by CSP and same-origin. Errors keep the existing envelope
`{"error": {"code": ..., "message": ...}}`.

`POST /appearance/import` accepts:

```json
{"preset": { "...": "preset without id/version required" }, "policy": "both"}
```

`policy: "both"` keeps an equally named custom preset and adds a unique
suffix; `policy: "replace"` updates the existing custom preset with that name.
Both stage the parsed preset (`staged: true`); nothing becomes active until an
explicit apply.

`POST /appearance/import/preview` takes the raw ZIP bytes (not JSON) with
`Content-Type: application/zip` (a missing type or `application/octet-stream`
is accepted because the bytes are validated regardless) and returns
`{preset, resources, comparison, warnings}`. `comparison` has
`sameAsActive` and `changed: {branding, colors, preferences}`; graphic fields
are compared by content hash, not by URL spelling.

## Portable ZIP

Export produces a real, self-contained ZIP (not a data URL dump):

```
preset.json
resources/logo.png
resources/favicon.ico
```

`preset.json` is:

```json
{
  "format": "asset-manager-appearance",
  "version": 1,
  "preset": {"...": "literal paths resources/<key>.<ext>"},
  "resources": [{"key": "logo", "name": "resources/logo.png", "type": "image/png"}]
}
```

Import validation happens entirely in memory before SQL or blob writes:

- ZIP size ≤ 24 MiB, entries ≤ 40, each expanded/compressed entry ≤ 8 MiB,
  total expanded ≤ 24 MiB, manifest ≤ 256 KiB.
- Stored or deflated only; encrypted entries rejected.
- Local and central names must match; duplicates (case-folded), directories,
  traversal, backslashes, NUL and unexpected entries rejected.
- Entry CRCs are verified by `zipfile`; compression ratio > 1000 on entries
  over 1 MiB is rejected.
- `format`/`version` must match; preset schema and resource index must be
  consistent; every referenced resource must exist and every extra file is
  rejected.
- Graphics are validated by actual bytes, not by extension or declared MIME:
  SVG (strict, defused XML), PNG, JPEG, WebP and ICO. A logo cannot be an ICO;
  a favicon cannot be WebP/JPEG. Favicon must be SVG, PNG or a real ICO.
- Any failure leaves stored presets, resources and active state unchanged.

## Storage

Graphic bytes are written through the configured opaque `BlobStorage`
(`settings.attachment_storage_path` by default) under random 32-hex keys.
SQL stores only content type, size, SHA-256, dimensions and the blob key.
Reads verify stored size and SHA-256 before serving; a missing or altered blob
is a 503, never partial bytes. Unreferenced resources are garbage-collected
after preset updates/deletes; built-ins never touch storage.

## Models and migration

Models live in `itsm/appearance/models.py` on `InventoryBase`:

- `AppearancePreset` → `appearance_presets`
  `id String(80) PK`, `name String(120) unique indexed`, `version Integer`,
  `description String(500)`, `document JSON`, `staged Boolean`,
  `created_by` / `updated_by String(160)`, `created_at` / `updated_at`
  `DateTime(timezone=True)`.
- `AppearanceResource` → `appearance_resources`
  `id String(32) PK`, `content_type String(64)`, `size Integer`,
  `sha256 String(64) unique indexed`, `blob_key String(32) unique`,
  `width` / `height Integer nullable`, `created_by String(160)`,
  `created_at DateTime(timezone=True)`.
- `AppearanceState` → `appearance_state`
  `id Integer PK`, `active_id String(80)`, `previous_id String(80) nullable`,
  `active JSON`, `previous JSON nullable`, `revision Integer`,
  `updated_by String(160)`, `updated_at DateTime(timezone=True)`.

The parent owns the Alembic revision that creates these three tables; the
module itself only defines metadata.

## Application wiring

```python
from itsm.appearance import build_appearance_service, create_appearance_router

app.state.appearance_service = build_appearance_service(
    settings, app.state.session_factory
)
api.include_router(create_appearance_router())
```

Mount the router under `settings.api_prefix` before the MCP mount, like the
other domain routers. The optional `storage=` argument accepts the same
`BlobStorage` implementation used by attachments. The canonical direct form
`AppearanceService(session, identity, settings, source="api")` is also
supported; `build_appearance_service` is the lifespan helper.

## Report branding seam

`itsm/reports/service.py` reads the active installation identity without
changing the report renderer:

- `appearance_report_branding(session)` supplies `name` (organization),
  `primary` and `accent` from the active light palette. Explicit report
  settings win over these defaults.
- `appearance_report_logo(session, settings, storage)` supplies a raster logo
  only when the active preset is not generic, no report logo attachment is
  configured, the stored type is PNG/JPEG/WebP, and bytes match the recorded
  size and SHA-256.
- Missing tables (pre-migration) degrade to the legacy report defaults.

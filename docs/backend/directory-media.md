# Directory floor-plan media

A directory floor can own one bounded raster plan. The browser uploads and
reads it through the canonical directory resource; the database never stores
file paths, URLs, or image bytes, and no new table or migration is required.

## Integration (main-router owner)

1. Import `create_directory_media_router` from `itsm.directory.media_api`.
2. In `create_app`, after `api.include_router(create_directory_router())` and
   before `app.include_router(api)` / the MCP mount, add:

   ```python
   api.include_router(create_directory_media_router())
   ```

   No lifespan hook, task, model, setting, or migration is needed. Storage uses
   the existing `settings.attachment_storage_path` under `directory-plans/`.

## HTTP contract

All routes live under `settings.api_prefix` (`/api/v1`).

| Method | Path | Permission |
| --- | --- | --- |
| `GET` | `/locations/{locationId}/plan` | `assets.view` |
| `GET` | `/locations/{locationId}/plan/meta` | `assets.view` |
| `PUT` | `/locations/{locationId}/plan` | `assets.view` + `config.sites` |
| `DELETE` | `/locations/{locationId}/plan` | `assets.view` + `config.sites` |

`PUT` and `DELETE` also require the existing cookie-session Origin + CSRF
guard; bearer machine calls keep their existing exemption.

`PUT` body is the raw image (`image/png`, `image/jpeg` or `image/webp`, decided
from magic bytes, declared `Content-Type` ignored). Limits: 5 MiB, 8192 px per
side, 25 million pixels and one fully decodable frame. Pillow decodes the full
payload before storage; truncated/corrupt replacements leave the prior blob intact.
A floor is the only location level that accepts a plan; any other level returns `422`.

Metadata response:

```json
{
  "locationId": "…",
  "planRef": "plan-<32 lowercase hex>",
  "planPage": "1600x1000",
  "contentType": "image/png",
  "width": 1600,
  "height": 1000,
  "size": 48213,
  "planUrl": "/locations/…/plan"
}
```

`planRef` is an opaque identifier (`plan-` + 32 hex), never a path or URL, so it
still passes the directory's existing `_plan_reference` validation. The
explorer resolves the image through `planUrl` relative to `api_prefix`; it must
not construct storage paths. `planPage` is `WIDTHxHEIGHT`.

Binary `GET` headers: `Content-Type` from the stored bytes,
`X-Plan-Width`, `X-Plan-Height`, `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, inline `Content-Disposition`.

Status codes:

- `404` no plan or unknown location (`not_found` envelope).
- `422` empty/oversized/non-raster/undecodable dimensions or non-floor location.
- `403` missing `config.sites`, Origin or CSRF on mutations.
- `503` storage unavailable (`local blob root` cannot be opened or the stored
  object is corrupt).
- `204` delete; deleting when no plan exists is idempotent.

Upload validates and stores the image first, then publishes `planRef`/
`planPage` through `DirectoryService.update_location` (same audit and change
validation as any location edit). If publishing fails, the previous bytes are
restored. Publishing is skipped when the reference and dimensions are already
current, so re-uploading identical metadata does not hit the "patch does not
change any field" guard.

## Storage

`LocalBlobStorage(settings.attachment_storage_path / "directory-plans")` with a
deterministic SHA-256 key of the location id (32 lowercase hex). Reads are
bounded, non-following, regular-file-only; writes are `0600`. Nothing about the
storage path is returned to clients.

## Explorer use

- On opening a floor, fetch `/locations/{id}/plan/meta`; if present, fetch
  `planUrl` as a blob and hand the object URL to a MapLibre image source over
  `[[0,1],[width/height,1],[width/height,0],[0,0]]`. Normalized asset x/y positions
  project into that aspect-preserving synthetic box; no geocoder is involved.
- Revoke object URLs on floor change/unmount.
- Camera FoV keeps using the existing authenticated
  `/assets/{id}/images/fov` resource; this module never duplicates or proxies it.
- `DELETE` clears both the blob and the location's `planRef`/`planPage`; the
  frontend should drop the cached object URL.

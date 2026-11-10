# Asset core: common fields, lifecycle, history and media

The canonical
`InventoryService` stays the only business layer: REST, the Pydantic AI tools
and the FastMCP server keep calling it, and nothing here adds a second
validation, SQL or permission path.

This document describes what is implemented. Three things are deliberately
**not** implemented yet and belong to the later integration step:

- the reusable field library and its catalog-driven validation (types,
  categories, per-category fields),
- the quick-code allocator / naming policy,
- the frontend fallback for a missing photo.

Until the catalog seam exists, `cost` and `technical` are validated by the
bounded rules below instead of by catalog metadata. They must not be treated as
custom fields. Free-text notes keep using the existing `description` field
(1000 characters); no duplicate `notes` column is introduced.

## Data model

Migration `0004_asset_core` (`down_revision = "0003_inventory"`) adds columns to
the existing `assets` table and three new tables. The catalog migration is an
independent sibling of the same parent and is merged later; this revision does
not touch catalog tables.

### New `assets` columns

| Column | Type | Rule |
|---|---|---|
| `cost` | `String(16)` | Stored as a two-decimal string; validated as a non-negative decimal `<= 1000000000` with at most 2 decimals. No binary float is stored. |
| `technical` | `JSON` | Flat map, at most 40 keys, key `^[A-Za-z][A-Za-z0-9_.-]{0,63}$`, values are text (`<= 500`), numbers (`|v| <= 10^12`), booleans or lists of those (at most 20 entries). Nested maps/lists are rejected. |
| `archived_at` | `DateTime(timezone=True)` | Set when archived, cleared on restore. Plain `NULL` means "not archived". |
| `archived_by` | `String(64)` | Username that archived the asset; cleared on restore. |

`archived` is therefore *derived* from `archived_at` and is completely separate
from `status`, `responsible` and `location`. Archiving never mutates them, and a
retirement never sets the archive flag.

### New tables

- `asset_history` — append-only trail. Columns: `id` (UUID), `sequence`
  (globally increasing counter, monotonically ordered within each asset), `asset_id`, `action`,
  `quick_code_old/new`, `status_old/new`, `archived_old/new`, `changes` (JSON,
  non-null), `reason`, `actor_id`, `actor_username`, `created_at`.
  Index `ix_asset_history_asset_sequence` on `(asset_id, sequence)`.
  There is no foreign key to `assets` on purpose: history outlives the asset.
- `asset_tombstones` — `id` (the purged asset UUID, primary key), `quick_code`,
  `purged_at`, `purged_by`, `reason` (non-null). A tombstone keeps the UUID
  reserved so `_new_asset_id()` never reissues it, even after the asset row and
  its media are gone.
- `asset_media` — `id`, `asset_id` (`FK assets.id ON DELETE CASCADE`), `role`,
  `content_type`, `size`, `data` (`LargeBinary`), `updated_by`,
  `created_at`, `updated_at`, unique `uq_asset_media_role` on `(asset_id, role)`.
  Small bounded images live in portable SQL blobs; no filesystem path, object
  store or external media service is introduced.

History actions: `created`, `updated`, `cloned`, `archived`, `restored`,
`retired`, `purged`. Each row records the actor identity and timestamp, the
quick code and lifecycle values before/after, and the reason when the operation
requires one. A purge writes a final `purged` row (old values → `null`) before
deleting the asset, so `GET /assets/{id}/history` still answers after a purge.

## Service API

`InventoryService(session, settings, *, identity=None)` — new and changed
methods. Permission checks run in the service, never in an adapter.

```python
create(principal, values) -> AssetView                     # assets.edit (+assets.assign if responsible)
update(principal, asset_id, changes) -> AssetView          # assets.edit (+assets.assign if responsible changes)
batch(principal, *, create=(), update=()) -> BatchResult   # all authorizations and validation before one commit
clone(principal, asset_id, changes=None) -> AssetView      # assets.edit (+assets.assign if a responsible is copied)
archive(principal, asset_id, *, reason=None) -> AssetView  # assets.edit
restore(principal, asset_id) -> AssetView                  # assets.edit
retire(principal, asset_id, *, reason) -> AssetView        # assets.edit (+assets.assign if responsible is set)
purge(principal, asset_id, *, confirm=False, typed_id=None, reason=None) -> PurgeResult
history(principal, asset_id, *, limit=DEFAULT_LIMIT, offset=0) -> HistoryPage  # assets.view
image(principal, asset_id, role) -> ImageContent           # assets.view
set_image(principal, asset_id, role, data) -> ImageView    # assets.edit
remove_image(principal, asset_id, role) -> None            # assets.edit
```

- `values`/`changes` stay camel-free dictionaries keyed by the service field
  names (`quick_code`, `cost`, `technical`, ...). `ASSET_FIELDS` is the accepted
  key set; unknown keys are rejected before any write.
- `clone` accepts an optional partial mapping of the same fields (no `id`), so
  a caller can override the generated quick code. It always allocates a new
  UUID, never inherits `archived_*`, never copies media, and records
  `reason="source:<id>"` in its `cloned` history row.
- Batch keeps the phase 3 contract: at most 50 operations, every item is
  authorized and validated before the first write, then one flush/commit.
  A denial or conflict leaves assets, history and media untouched; only the
  denied audit event exists.
- Amounts are returned as strings (`"1250.50"`), never floats, so a client does
  not lose cents through JSON number formatting.

`AssetView` adds `cost: Decimal | None`, `technical: Mapping | None`,
`archived: bool`, `archived_at`, `archived_by`, `images: Mapping[str, str]`.
`as_payload()` serialises them as `cost` (string or null), `technical`, and
`archived`, `archivedAt`, `archivedBy`, `images`. Image bytes are never part of
the DTO: `images` maps the present roles to their read URL.

## REST API

All routes live under the existing prefix (`/api/v1`) and keep the phase 3
status codes and error envelope `{"error": {"code", "message"}}`.

| Method and path | Success | Permission / guards |
|---|---|---|
| `GET /assets/search` | 200 | `assets.view`; filters `query`, `category`, `site`, `status`, `quickCode`, `id`, `archived`, `limit`, `offset` |
| `GET /assets` | 200 | `assets.view`; same filters, page envelope |
| `POST /assets` | 201 | `assets.edit`; mutation guard (Origin + CSRF) |
| `POST /assets/batch` | 200 | `assets.edit`; per-item `assets.assign` when a responsible is set |
| `GET /assets/{asset_id}` | 200 | `assets.view` |
| `PATCH /assets/{asset_id}` | 200 | `assets.edit`; `assets.assign` only when the responsible changes |
| `POST /assets/{asset_id}/clone` | 201 | `assets.edit`; `assets.assign` only when copying a responsible |
| `POST /assets/{asset_id}/archive` | 200 | `assets.edit`; body `{"reason": "..."}` optional |
| `POST /assets/{asset_id}/restore` | 200 | `assets.edit` |
| `POST /assets/{asset_id}/retire` | 200 | `assets.edit`; `assets.assign` when a responsible is cleared; body `{"reason": "..."}` (4–500 chars) |
| `POST /assets/{asset_id}/purge` | 200 | see the purge policy below |
| `GET /assets/{asset_id}/history` | 200 | `assets.view`; `limit` 1–200, `offset >= 0` |
| `GET /assets/{asset_id}/images/{role}` | 200 | `assets.view` (human or machine) |
| `PUT /assets/{asset_id}/images/{role}` | 200 | `assets.edit`; raw body, `Content-Type` ignored |
| `DELETE /assets/{asset_id}/images/{role}` | 200 | `assets.edit` |

`archived` is a tri-state query filter: `true` returns only archived assets,
`false` only active ones, absent returns both. It is not a replacement for
`status`.

The asset payload is the phase 3 DTO plus the six new keys:

```json
{
  "id": "…", "quickCode": "SW-SN-001", "name": "…",
  "category": "Red", "type": "Switch", "brand": "…", "model": "…",
  "serial": "…", "ip": "192.168.50.11", "site": "Sede Norte",
  "location": "Rack 2", "responsible": "Matriz NOC", "status": "in_use",
  "description": "…", "cost": "1250.50", "technical": {"ramGb": 16},
  "archived": false, "archivedAt": null, "archivedBy": null,
  "images": {}, "createdAt": "…", "updatedAt": "…"
}
```

History payload: `id`, `sequence`, `assetId`, `action`, `quickCodeOld`,
`quickCodeNew`, `statusOld`, `statusNew`, `archivedOld`, `archivedNew`,
`changes` (`{field: {"old", "new"}}`), `reason`, `actorId`, `actorUsername`,
`createdAt`. The page envelope adds `assetId`, `total`, `limit`, `offset`.

Image payload: `role`, `contentType`, `size`, `url`, `updatedAt`. The binary
route answers the validated bytes with the sniffed content type and the headers
`Cache-Control: private, no-store`, `Content-Length` and
`X-Content-Type-Options: nosniff`.

## Purge policy

`purge()` is the only destructive operation and it is deliberately narrow.

| Environment | Requirements |
|---|---|
| any | Actor must be a human identity. A machine actor is refused and audited as a denied `assets.purge`, even if its role carries the permission. |
| `production` | `assets.purge` privilege, asset already archived, `confirm is True`, `typed_id` equal to the asset UUID, reason of 4–500 characters. |
| `development`, `test` | `assets.edit`, explicit `confirm=True`; typed id and reason are optional. |

The distinct `assets.purge` code is seeded for the built-in `admin` role by this
migration and is listed in `MACHINE_FORBIDDEN_PERMISSIONS`, so no machine
identity can hold it effectively. `assets.purge` is intentionally not part of
the operator or reader roles. The environment comes exclusively from
`Settings.environment`; no request value can switch the mode.

A successful purge deletes the media rows, writes the tombstone and the final
history row, deletes the asset, and audits `inventory.asset_purged` against
`asset:<quick_code>`. Nothing else is removed, and the UUID stays reserved.

## Media policy

- Roles are exactly `photo` and `fov`; anything else (including path-like text)
  is rejected with `ValidationFailed`.
- `fov` requires the asset category to name a camera
  (`camera`, `camara`, `cctv`, `ipcam` prefixes, accent/case insensitive).
- Only bytes are accepted: at most 1 MiB and a signature of PNG, JPEG, WebP or
  GIF. The transport `Content-Type` is never trusted nor echoed. SVG, HTML,
  scripts and `data:` URLs are rejected by signature, and no path or URL is ever
  read, so a remote fetch or traversal is structurally impossible.
- `PUT` validates everything before the first write, then inserts or replaces
  the single row for that role. `DELETE` removes one role and leaves the other
  role and the asset untouched. Both are audited
  (`inventory.asset_image_updated`, `inventory.asset_image_removed`); the purge
  deletes media rows without a separate media audit.

## Errors

| Rule | Error | HTTP |
|---|---|---|
| Invalid field, cost, ip, technical, role, image bytes, missing reason, unconfirmed purge, missing typed id | `ValidationFailed` | 422 `validation_error` |
| Unknown asset, unknown image role state | `NotFound` | 404 `not_found` |
| Duplicate quick code (case-insensitive), archived twice, restore of an active asset, retire twice, purge of a non-archived production asset | `Conflict` | 409 `conflict` |
| Missing permission or machine purge | `PermissionDenied` | 403 `forbidden` |

## Verification limits

Covered by `tests/test_asset_core.py`, `tests/test_asset_media.py` and
`tests/test_asset_lifecycle_api.py` on isolated SQLite databases: sparse assets,
cost/technical rules, clone identity and assignment authorization, archive
versus status/responsible/location, restore, retirement reason and assignment,
history contents and survival of a purge, tombstone id reservation, the
development/test and production purge matrices, batch atomicity, media
validation, media role independence and read-only identities.

Not covered here: catalog-driven validation and the quick-code allocator (not
implemented), the frontend photo fallback, and any claim about PostgreSQL,
MariaDB or MSSQL beyond the existing validation matrix. No security
certification is implied.

## Migration and integration notes

- Revision `0004_asset_core` depends on `0003_inventory` only. The catalog
  migration is a sibling of the same parent; whichever is merged later must keep
  both against `0003_inventory` (or rebase onto the merged head).
- This revision seeds one row in `identity_role_policies` (`admin`,
  `assets`, `purge`). Downgrade removes exactly that row and drops the three
  tables and four columns.
- Models live in `itsm/inventory/models.py` on the existing `InventoryBase`, so
  `migrations/env.py` discovers them without changes.
- The authorization entry point stays `IdentityService.authorize`; the new code
  adds no bypass, no startup bootstrap and no seed of asset data.
